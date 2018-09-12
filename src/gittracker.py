import argparse
import difflib
import itertools
import json
import logging
import subprocess
import re
import typing


class GitWrapper:
    def __init__(self, git_bin: str, git_dir: str):
        self._logger = logging.getLogger('%s.%s' % (__name__, 'GitWrapper'))
        self._encoding = 'utf-8'
        self._git_bin = git_bin
        self._git_dir = git_dir

    def _git_cmd(self, *args) -> typing.List[str]:
        self._logger.debug('Executing git with %s' % ' '.join(args))
        arguments = [self._git_bin, '--git-dir', self._git_dir, *args]
        output = subprocess.check_output(arguments, stderr=subprocess.STDOUT)
        return [
            line.decode(self._encoding, errors='replace')
            for line in output.split(b'\n') if line
        ]

    def get_branches(self, remote: str, pattern: str) -> typing.List[str]:
        self._logger.info('Getting branches list for %s/%s' % (remote, pattern))
        pattern = re.compile(r'%s/(%s)' % (remote, pattern), re.IGNORECASE)
        lines = self._git_cmd('branch', '-ar')

        result = []
        for line in lines:
            line = line.strip()
            if re.match(pattern, line):
                branch = line.rsplit('/', 2)[-1]
                result.append(branch)

        return result

    def get_merge_base(self, ref_subject: str, ref_target: str) -> str:
        self._logger.info('Getting merge-base for %s %s' % (ref_subject, ref_target))
        return self._git_cmd('merge-base', ref_subject, ref_target)[0]

    def get_diff_files(self, ref_subject: str, ref_target: str) -> typing.List[str]:
        self._logger.info('Getting changed files for %s %s' % (ref_subject, ref_target))
        return self._git_cmd('diff', '--name-only', ref_subject, ref_target)

    def get_blame_file(self, rev: str, filepath: str) -> typing.List[dict]:
        self._logger.info('Getting file blame for %s %s' % (rev, filepath))

        try:
            output = self._git_cmd('blame', '--line-porcelain', rev, '--', filepath)
        except subprocess.CalledProcessError as e:
            # Файла в ревизии нет.
            if e.returncode == 128:
                output = []

            # Произошло что-то плохое.
            else:
                raise

        result = []
        position = 0
        blockinfo = {}

        while position < len(output):
            line = output[position]

            if not blockinfo:
                info = line.split()
                blockinfo['hash'] = info[0]
                blockinfo['lineno'] = info[2]

            elif line.startswith('author '):
                blockinfo['author'] = line[len('author '):]

            elif line.startswith('author-mail '):
                blockinfo['author-mail'] = line[len('author-mail '):]

            elif line.startswith('author-time '):
                blockinfo['author-time'] = line[len('author-time '):]

            elif line.startswith('author-tz '):
                blockinfo['author-tz'] = line[len('author-tz '):]

            elif line.startswith('committer '):
                blockinfo['committer'] = line[len('committer '):]

            elif line.startswith('committer-mail '):
                blockinfo['committer-mail'] = line[len('committer-mail '):]

            elif line.startswith('committer-time '):
                blockinfo['committer-time'] = line[len('committer-time '):]

            elif line.startswith('committer-tz '):
                blockinfo['committer-tz'] = line[len('committer-tz '):]

            elif line.startswith('summary '):
                blockinfo['summary'] = line[len('summary '):]

            elif line.startswith('filename '):
                blockinfo['filename'] = line[len('filename '):]

            elif line.startswith('previous '):
                blockinfo['previous'] = line[len('previous '):]

            elif line.startswith('\t'):
                blockinfo['content'] = line[len('\t'):]

                # Признак конца блока - строка с содержимым.
                result.append(blockinfo)

                # Старт заполнения следующего блока.
                blockinfo = {}

            else:
                raise Exception('Unexpected line: %s' % line)

            position += 1

        return result


class GitTracker:
    def __init__(self, wrapper: GitWrapper, ignored: typing.List[str]):
        self._logger = logging.getLogger('%s.%s' % (__name__, 'GitTracker'))
        self._wrapper = wrapper
        self._ignored = ignored

    def track(self, remote: str, pattern: str) -> typing.List[dict]:
        self._logger.info('Tracking branches for %s/%s' % (remote, pattern))
        for branch in self._wrapper.get_branches(remote, pattern):
            if branch not in self._ignored:
                yield remote, branch, self._track_branch(remote, branch)

    def _track_branch(self, remote: str, branch: str):
        self._logger.debug('Tracking branch %s/%s' % (remote, branch))
        merge_base = wrapper.get_merge_base('%s/%s' % (remote, branch), '%s/master' % remote)
        diff_files = wrapper.get_diff_files('%s/%s' % (remote, branch), merge_base)
        for file_path in diff_files:
            yield file_path, self._track_file(branch, file_path)

    def _track_file(self, branch: str, file_path: str):
        self._logger.debug('Tracking file %s' % file_path)
        blame_branch = wrapper.get_blame_file('origin/%s' % branch, file_path)
        blame_master = wrapper.get_blame_file('origin/master', file_path)

        matcher = difflib.SequenceMatcher(None)
        matcher.set_seq1([x['content'].strip() for x in blame_master])
        matcher.set_seq2([x['content'].strip() for x in blame_branch])

        for tag, m1, m2, b1, b2 in matcher.get_opcodes():
            if tag != 'equal' and self._track_needed(blame_master[m1:m2], blame_branch[b1:b2]):
                yield blame_master[m1:m2], blame_branch[b1:b2]

    def _track_needed(self, blames_master: typing.List[dict], blames_branch: typing.List[dict]) -> bool:
        authors_master = {x['author-mail'] for x in blames_master}
        authors_branch = {x['author-mail'] for x in blames_branch}
        return bool(authors_master - authors_branch)


class GitReporter:
    def __init__(self, emails: typing.List[str]):
        self._emails = set(emails)

    def display(self, changes: typing.List[dict]):
        for remote, branch, branch_changes in changes:
            header_shown = False

            for file_path, file_changes in branch_changes:
                for blames_master, blames_branch in file_changes:
                    authors_master = {x['author-mail'].strip('<>') for x in blames_master}
                    authors_branch = {x['author-mail'].strip('<>') for x in blames_branch}

                    if self._emails & authors_master and not self._emails & authors_branch:
                        if not header_shown:
                            header = 'Branch %s/%s' % (remote, branch)
                            print(self._display_branch_header())
                            print(self._display_branch_content(header))
                            print(self._display_branch_footer())
                            header_shown = True

                        header = 'Changes for branch %s/%s file %s' % (remote, branch, file_path)
                        print(self._display_block_header())
                        print(self._display_block_content(header))
                        print(self._display_diff_header())

                        left_lines = []
                        right_lines = []

                        for blame_master in blames_master:
                            left_lines.append(self._display_diff_line(
                                blame_master['author-mail'],
                                blame_master['lineno'],
                                blame_master['content'],
                            ))

                        for blame_branch in blames_branch:
                            right_lines.append(self._display_diff_line(
                                blame_branch['author-mail'],
                                blame_branch['lineno'],
                                blame_branch['content'],
                            ))

                        lines_pairs = itertools.zip_longest(left_lines, right_lines)
                        for index, (left_line, right_line) in enumerate(lines_pairs):
                            if not left_line:
                                left_line = 'Absent in master' if index == 0 else ''
                                left_line = self._display_diff_line('', '', left_line)

                            if not right_line:
                                right_line = 'Absent in %s' % branch if index == 0 else ''
                                right_line = self._display_diff_line('', '', right_line)

                            print(self._display_diff_lines(left_line, right_line))

                        print(self._display_diff_footer())

    def _display_branch_header(self):
        return '╔' + '═' * 275 + '╗'

    def _display_branch_content(self, content):
        return '║' + ' %-273s ' % content + '║'

    def _display_branch_footer(self):
        return '╚' + '═' * 275 + '╝'

    def _display_block_header(self):
        return '┌' + '─' * 275 + '┐'

    def _display_block_content(self, content):
        return '│' + ' %-273s ' % content + '│'

    def _display_diff_header(self):
        part = '─' * 27 + '┬' + '─' * 6 + '┬' + '─' * 102
        return '├' + part + '┬' + part + '┤'

    def _display_diff_line(self, email, lineno, content):
        email = '%s' % email.strip('<>')[:23]
        return '%-25s │ %-4s │ %s' % (email, lineno, content[:100])

    def _display_diff_lines(self, left_line, right_line):
        return '│ %-135s │ %-135s │' % (left_line, right_line)

    def _display_diff_footer(self):
        part = '─' * 27 + '┴' + '─' * 6 + '┴' + '─' * 102
        return '└' + part + '┴' + part + '┘'


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--repopath', required=True, help='Path to git repo on disk')
    parser.add_argument('--remote', required=True, help='Git remote, f.e. "origin"')
    parser.add_argument('--pattern', required=True, help='Filter branches regexp')
    parser.add_argument('--email', required=True, nargs='+', help='Emails to track')
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING)
    wrapper = GitWrapper('git', args.repopath.rstrip('/') + '/.git')
    tracker = GitTracker(wrapper, json.load(open('ignored.json')))
    changes = tracker.track(args.remote, args.pattern)
    reporter = GitReporter(args.email)
    reporter.display(changes)
