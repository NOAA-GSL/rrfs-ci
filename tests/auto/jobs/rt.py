"""
Name: rt.py
Python to clone and build a weather model repo and run
regression tests.
"""

# Imports
import datetime
import logging
import os


def run(job_obj):
    """
    Runs a baseline test for a weather model PR
    """
    logger = logging.getLogger('RT/RUN')
    logger.info('Started running regression test')
    pr_repo_loc, repo_dir_str = clone_pr_repo(job_obj, job_obj.workdir)
    logger.info(f'pr_repo_loc is: {pr_repo_loc}')
    logger.info(f'repo_dir_str is: {repo_dir_str}')
    run_regression_test(job_obj, pr_repo_loc)
    post_process(job_obj, pr_repo_loc, repo_dir_str)
    logger.info('Finished running regression test')


def run_regression_test(job_obj, pr_repo_loc):
    logger = logging.getLogger('RT/RUN_REGRESSION_TEST')
    logger.info('Started run_regression_test')
    if job_obj.compiler == 'gnu':
        rt_command = [[f'export RT_COMPILER="{job_obj.compiler}" && cd tests '
                       '&& /bin/bash --login ./rt.sh -r -k -l rt_gnu.conf >& gnu_out',
                       pr_repo_loc]]
    elif job_obj.compiler == 'intel':
        rt_command = [[f'export RT_COMPILER="{job_obj.compiler}" && cd tests '
                       '&& /bin/bash --login ./rt.sh -r -k >& intel_out', pr_repo_loc]]
    job_obj.run_commands(logger, rt_command)
    logger.info('Finished run_regression_test')


def remove_pr_data(job_obj, pr_repo_loc, repo_dir_str, rt_dir):
    logger = logging.getLogger('RT/REMOVE_PR_DATA')
    logger.info('Started remove_pr_data')
    rm_command = [
                 [f'rm -rf {rt_dir}', pr_repo_loc],
                 [f'rm -rf {repo_dir_str}', pr_repo_loc]
                 ]
    job_obj.run_commands(logger, rm_command)
    logger.info('Finished remove_pr_data')


def clone_pr_repo(job_obj, workdir):
    ''' clone the GitHub pull request repo, via command line '''
    logger = logging.getLogger('RT/CLONE_PR_REPO')
    logger.info('Started clone_pr_repo')
    repo_name = job_obj.preq_dict['preq'].head.repo.full_name
    branch = job_obj.preq_dict['preq'].head.ref
    app_name = job_obj.repo["app_address"].split("/")[1]
    git_url = f'https://${{ghapitoken}}@github.com/{repo_name}'
    logger.debug(f'GIT URL: {git_url}')
    repo_dir_str = f'{workdir}/pr/'\
                   f'{str(job_obj.preq_dict["preq"].id)}/'\
                   f'{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}'
    pr_repo_loc = f'{repo_dir_str}/{app_name}'
    job_obj.comment_append(f'Repo location: {pr_repo_loc}')
    create_repo_commands = [
        [f'mkdir -p "{repo_dir_str}"', os.getcwd()],
        [f'git clone -b {branch} {git_url} {app_name}', repo_dir_str],
        ['git submodule update --init --recursive',
         f'{repo_dir_str}/{app_name}'],
        ['git config user.email "venita.hagerty@noaa.gov"',
         f'{repo_dir_str}/{app_name}'],
        ['git config user.name "venitahagerty"',
         f'{repo_dir_str}/{app_name}']
    ]

    job_obj.run_commands(logger, create_repo_commands)

    logger.info('Finished clone_pr_repo')
    return pr_repo_loc, repo_dir_str


def post_process(job_obj, pr_repo_loc, repo_dir_str):
    ''' This is the callback function associated with the "RT" command '''
    logger = logging.getLogger('RT/POST_PROCESS')
    logger.info('Started post_process')
    rt_log = f'tests/RegressionTests_{job_obj.machine}'\
             f'.{job_obj.compiler}.log'
    filepath = f'{pr_repo_loc}/{rt_log}'
    rt_dir, logfile_pass = process_logfile(job_obj, filepath)
    if logfile_pass:
        job_obj.comment_append('Regression test successful')
        # remove_pr_data(job_obj, pr_repo_loc, repo_dir_str, rt_dir)
    else:
        job_obj.comment_append('Regression test FAILED')
    issue_id = job_obj.send_comment_text()
    logger.debug(f'Issue comment id is {issue_id}')
    logger.info('Finished post_process')


def process_logfile(job_obj, logfile):
    logger = logging.getLogger('RT/PROCESS_LOGFILE')
    logger.info('Started process_logfile')
    rt_dir = []
    fail_string_list = ['Test', 'failed']
    if os.path.exists(logfile):
        with open(logfile) as f:
            for line in f:
                if all(x in line for x in fail_string_list):
                    # if 'FAIL' in line and 'Test' in line:
                    job_obj.comment_append(f'{line.rstrip(chr(10))}')
                elif 'working dir' in line and not rt_dir:
                    rt_dir = os.path.split(line.split()[-1])[0]
                    job_obj.comment_append(f'Please manually delete: '
                                           f'{rt_dir}')
                elif 'SUCCESSFUL' in line:
                    logger.info('RT Successful')
                    logger.info('Finished process_logfile')
                    return rt_dir, True
        logger.critical('Log file exists but is not complete')
        job_obj.job_failed(logger, f'{job_obj.preq_dict["action"]}')
    else:
        logger.critical(f'Could not find {job_obj.machine}'
                        f'.{job_obj.compiler} '
                        f'{job_obj.preq_dict["action"]} log')
        print(f'Could not find {job_obj.machine}.{job_obj.compiler} '
              f'{job_obj.preq_dict["action"]} log')
        raise FileNotFoundError
