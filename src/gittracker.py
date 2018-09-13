import argparse
import datetime
import difflib
import itertools
import logging
import subprocess
import re
from typing import List, Tuple

wrapper_logger = logging.getLogger('%s.%s' % (__name__, 'GitWrapper'))
tracker_logger = logging.getLogger('%s.%s' % (__name__, 'GitTracker'))


class GitWrapper:
    def __init__(self, git_bin: str, git_dir: str):
        self._encoding = 'utf-8'
        self._git_bin = git_bin
        self._git_dir = git_dir

    def _git_cmd(self, *args) -> List[str]:
        wrapper_logger.debug('Executing git with %s' % ' '.join(args))
        arguments = [self._git_bin, '--git-dir', self._git_dir, *args]
        output = subprocess.check_output(arguments, stderr=subprocess.STDOUT)
        return [
            line.decode(self._encoding, errors='replace')
            for line in output.split(b'\n') if line
        ]

    def get_branches(self, remote: str) -> List[Tuple[str, datetime.datetime]]:
        wrapper_logger.info('Getting branches list for %s' % remote)
        lines = self._git_cmd('branch', '-ar', '--format=%(refname:short) %(authordate:raw)')
        pattern = re.compile(r'%s/.*' % remote, re.IGNORECASE)

        result = []
        for line in lines:
            if pattern.match(line):
                branch, timestamp, tzone = line.split()
                branch = branch.rsplit('/', 2)[-1].strip()
                authordate = datetime.datetime.fromtimestamp(int(timestamp))
                result.append((branch, authordate))

        return result

    def get_merge_base(self, ref_subject: str, ref_target: str) -> str:
        wrapper_logger.info('Getting merge-base for %s %s' % (ref_subject, ref_target))
        return self._git_cmd('merge-base', ref_subject, ref_target)[0]

    def get_diff_files(self, ref_subject: str, ref_target: str) -> List[str]:
        wrapper_logger.info('Getting changed files for %s %s' % (ref_subject, ref_target))
        return self._git_cmd('diff', '--name-only', ref_subject, ref_target)

    def get_blame_file(self, rev: str, filepath: str) -> List[dict]:
        wrapper_logger.info('Getting file blame for %s %s' % (rev, filepath))

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
    def __init__(
        self,
        wrapper: GitWrapper,
        remote: str,
        branches: List[str] = None,
        no_branches: List[str] = None,
        files: List[str] = None,
        no_files: List[str] = None,
        after_date: datetime.datetime = None,
        before_date: datetime.datetime = None,
    ):
        self._wrapper = wrapper
        self._remote = remote
        self._branches = branches
        self._no_branches = no_branches
        self._files = files
        self._no_files = no_files
        self._after_date = after_date
        self._before_date = before_date

    def track(self) -> List[dict]:
        tracker_logger.info('Tracking branches for %s' % self._remote)
        include = re.compile(r'|'.join(self._branches or []), re.IGNORECASE)
        exclude = re.compile(r'|'.join(self._no_branches or []), re.IGNORECASE)
        branches = self._wrapper.get_branches(self._remote)

        for branch, authordate in branches:
            if self._branches and not include.search(branch):
                continue

            if self._no_branches and exclude.search(branch):
                continue

            if self._after_date and authordate < self._after_date:
                continue

            if self._before_date and authordate > self._before_date:
                continue

            yield self._remote, branch, self._track_branch(branch)

    def _track_branch(self, branch: str):
        tracker_logger.debug('Tracking branch %s' % branch)

        include = re.compile(r'|'.join(self._files or []), re.IGNORECASE)
        exclude = re.compile(r'|'.join(self._no_files or []), re.IGNORECASE)

        branch_full = '%s/%s' % (self._remote, branch)
        master_full = '%s/master' % self._remote
        merge_base = self._wrapper.get_merge_base(branch_full, master_full)
        diff_files = self._wrapper.get_diff_files(branch_full, merge_base)

        for file_path in diff_files:
            if self._files and not include.search(file_path):
                continue

            if self._no_files and exclude.search(file_path):
                continue

            yield file_path, self._track_file(branch, file_path)

    def _track_file(self, branch: str, file_path: str):
        tracker_logger.debug('Tracking file %s' % file_path)

        blame_branch = wrapper.get_blame_file('%s/%s' % (self._remote, branch), file_path)
        blame_master = wrapper.get_blame_file('%s/master' % self._remote, file_path)

        matcher = difflib.SequenceMatcher(None)
        matcher.set_seq1([x['content'].strip() for x in blame_master])
        matcher.set_seq2([x['content'].strip() for x in blame_branch])

        for tag, m1, m2, b1, b2 in matcher.get_opcodes():
            if tag == 'equal':
                continue

            authors_master = {x['author-mail'] for x in blame_master[m1:m2]}
            authors_branch = {x['author-mail'] for x in blame_branch[b1:b2]}
            if not authors_master - authors_branch:
                continue

            yield blame_master[m1:m2], blame_branch[b1:b2]


class GitReporter:
    def __init__(self, emails: List[str] = None):
        self._owners = set(emails) if emails else None

    def display(self, changes: List[dict]):
        for remote, branch, branch_changes in changes:
            branch_header_shown = False

            for file_path, file_changes in branch_changes:
                file_header_shown = False

                for blames_master, blames_branch in file_changes:
                    authors_master = {x['author-mail'].strip('<>') for x in blames_master}
                    authors_branch = {x['author-mail'].strip('<>') for x in blames_branch}

                    # Фильтр по email включен и в мастере нет указанных email-ов.
                    if self._owners and not self._owners & authors_master:
                        continue

                    # Фильтр по email включен и в ветке есть email-ы не из мастера.
                    if self._owners and not authors_branch - authors_master:
                        continue

                    if not branch_header_shown:
                        header = 'Branch %s/%s' % (remote, branch)
                        print(self._display_branch_header())
                        print(self._display_branch_content(header))
                        print(self._display_branch_footer())
                        branch_header_shown = True

                    if not file_header_shown:
                        header = 'Changes for branch %s/%s file %s' % (remote, branch, file_path)
                        print(self._display_block_header())
                        print(self._display_block_content(header))
                        print(self._display_diff_header())
                        file_header_shown = True
                    else:
                        print(self._display_block_ruler())

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

                if file_header_shown:
                    print(self._display_diff_footer())

    def _display_branch_header(self):
        return '╔' + '═' * 275 + '╗'

    def _display_branch_content(self, content):
        return '║' + ' %-273s ' % content + '║'

    def _display_branch_footer(self):
        return '╚' + '═' * 275 + '╝'

    def _display_block_header(self):
        return '┌' + '─' * 275 + '┐'

    def _display_block_ruler(self):
        return '│' + ' %-273s ' % ('╶' * 273) + '│'

    def _display_block_content(self, content):
        return '│' + ' %-273s ' % content + '│'

    def _display_diff_header(self):
        part = '─' * 27 + '┬' + '─' * 6 + '┬' + '─' * 102
        return '├' + part + '┬' + part + '┤'

    def _display_diff_line(self, email, lineno, content):
        email = '%s' % email.strip('<>')[:25]
        return '%-25s │ %-4s │ %s' % (email, lineno, content[:100])

    def _display_diff_lines(self, left_line, right_line):
        return '│ %-135s │ %-135s │' % (left_line, right_line)

    def _display_diff_footer(self):
        part = '─' * 27 + '┴' + '─' * 6 + '┴' + '─' * 102
        return '└' + part + '┴' + part + '┘'


if __name__ == '__main__':
    def parse_date(s):
        try:
            return datetime.datetime.strptime(s, '%Y-%m-%d')
        except ValueError:
            msg = 'Invalid date format: %s.' % s
            raise argparse.ArgumentTypeError(msg)

    parser = argparse.ArgumentParser()
    parser.add_argument('--gitpath', default='git', help='Path to git binary on disk')
    parser.add_argument('--repopath', required=True, help='Path to git repo on disk')
    parser.add_argument('--logging', default='FATAL', help='Logging to stderr level')
    parser.add_argument('--remote', default='origin', help='Git remote repository')
    parser.add_argument('--owners', nargs='+', help='Code owners emails to track')
    parser.add_argument('--branches', nargs='+', help='Include branches regexp')
    parser.add_argument('--no-branches', nargs='+', help='Exclude branches regexp')
    parser.add_argument('--files', nargs='+', help='Include files regexp')
    parser.add_argument('--no-files', nargs='+', help='Exclude files regexp')
    parser.add_argument('--after-date', type=parse_date, help='Changes after date, YYYY-mm-dd')
    parser.add_argument('--before-date', type=parse_date, help='Changes before date, YYYY-mm-dd')
    args = parser.parse_args()

    level = logging.getLevelName(args.logging)
    wrapper_logger.disabled = level != logging.NOTSET
    logging.basicConfig(level=level, format='[%(asctime)s %(levelname)-5s] %(message)s')

    wrapper = GitWrapper(args.gitpath, args.repopath.rstrip('/') + '/.git')
    GitReporter(args.owners).display(GitTracker(
        wrapper, args.remote,
        args.branches, args.no_branches,
        args.files, args.no_files,
        args.after_date, args.before_date,
    ).track())
