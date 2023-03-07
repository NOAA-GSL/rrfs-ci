"""
Name: bl.py
Python to clone and build a weather model repo and run baseline
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
    logger = logging.getLogger('BL/RUN')
    logger.info('Started running baseline test')
    blstore = f'{job_obj.workdir}/RT'
    logger.info(f'blstore is: {blstore}')
    user_name = os.environ['USER']
    rtbldir = f'{job_obj.workdir}/stmp4/{user_name}/FV3_RT/REGRESSION_TEST_{job_obj.compiler.upper()}'
    logger.info(f'rtbldir is: {rtbldir}')
    pr_repo_loc, repo_dir_str = clone_pr_repo(job_obj, job_obj.workdir)
    logger.info(f'pr_repo_loc is: {pr_repo_loc}')
    logger.info(f'repo_dir_str is: {repo_dir_str}')
    bldate = get_bl_date(job_obj, pr_repo_loc)
    bldir = f'{blstore}/NEMSfv3gfs/gsl-develop-{bldate}/{job_obj.compiler.upper()}'
    logger.info(f'bldir is: {bldir}')
    bldirbool = check_for_bl_dir(bldir, job_obj)
    if not bldirbool:
        run_regression_test(job_obj, pr_repo_loc)
        post_process(job_obj, pr_repo_loc, repo_dir_str, rtbldir, bldir)
    logger.info('Finished running baseline test')


def check_for_bl_dir(bldir, job_obj):
    logger = logging.getLogger('BL/CHECK_FOR_BL_DIR')
    logger.info('Checking if baseline directory exists')
    if os.path.exists(bldir):
        logger.critical(f'Baseline dir: {bldir} exists. It should not, yet.')
        job_obj.comment_append(f'{bldir}\n Exists already. '
                               'It should not yet. Please delete.')
        raise FileExistsError
    logger.info('Finished checking for baseline dir')

    return False


def create_bl_dir(bldir, job_obj):
    logger = logging.getLogger('BL/CREATE_BL_DIR')
    logger.info('Started create_bl_dir')
    if not check_for_bl_dir(bldir, job_obj):
        os.makedirs(bldir)
        if not os.path.exists(bldir):
            logger.critical(f'Someting went wrong creating {bldir}')
            raise FileNotFoundError
    logger.info('Finished create_bl_dir')


def run_regression_test(job_obj, pr_repo_loc):
    logger = logging.getLogger('BL/RUN_REGRESSION_TEST')
    logger.info('Started run_regression_test')
    if job_obj.compiler == 'gnu':
        rt_command = [[f'export RT_COMPILER="{job_obj.compiler}" && cd tests '
                       '&& /bin/bash --login ./rt.sh -r -c -k -l rt_gnu.conf >& gnu_out',
                       pr_repo_loc]]
    elif job_obj.compiler == 'intel':
        rt_command = [[f'export RT_COMPILER="{job_obj.compiler}" && cd tests '
                       '&& /bin/bash --login ./rt.sh -r -c -k >& intel_out', pr_repo_loc]]
    job_obj.run_commands(logger, rt_command)
    logger.info('Finished run_regression_test')


def remove_pr_data(job_obj, pr_repo_loc, repo_dir_str, rt_dir):
    logger = logging.getLogger('BL/REMOVE_PR_DATA')
    logger.info('Started remove_pr_data')
    rm_command = [
                 [f'rm -rf {rt_dir}', pr_repo_loc],
                 [f'rm -rf {repo_dir_str}', pr_repo_loc]
                 ]
    job_obj.run_commands(logger, rm_command)
    logger.info('Finished remove_pr_data')


def clone_pr_repo(job_obj, workdir):
    ''' clone the GitHub pull request repo, via command line '''
    logger = logging.getLogger('BL/CLONE_PR_REPO')
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


def post_process(job_obj, pr_repo_loc, repo_dir_str, rtbldir, bldir):
    logger = logging.getLogger('BL/POST_PROCESS')
    logger.info('Started post_process')
    rt_log = f'tests/RegressionTests_{job_obj.machine}'\
             f'.{job_obj.compiler}.log'
    filepath = f'{pr_repo_loc}/{rt_log}'
    rt_dir, logfile_pass = process_logfile(job_obj, filepath)
    if logfile_pass:
        create_bl_dir(bldir, job_obj)
        move_bl_command = [[f'mv {rtbldir}/* {bldir}/', pr_repo_loc]]
        job_obj.run_commands(logger, move_bl_command)
        job_obj.comment_append('Baseline creation and move successful')
        # remove_pr_data(job_obj, pr_repo_loc, repo_dir_str, rt_dir)
    else:
        job_obj.comment_append('Baseline creation FAILED')
    issue_id = job_obj.send_comment_text()
    logger.debug(f'Issue comment id is {issue_id}')
    logger.info('Finished post_process')


def get_bl_date(job_obj, pr_repo_loc):
    logger = logging.getLogger('BL/GET_BL_DATE')
    logger.info('Started get_bl_date')
    BLDATEFOUND = False
    with open(f'{pr_repo_loc}/tests/rt.sh', 'r') as f:
        for line in f:
            if 'BL_DATE=' in line:
                logger.info('Found BL_DATE in line')
                BLDATEFOUND = True
                bldate = line
                bldate = bldate.rstrip('\n')
                bldate = bldate.replace('BL_DATE=', '')
                bldate = bldate.strip(' ')
                logger.info(f'bldate is "{bldate}"')
                logger.info(f'Type bldate: {type(bldate)}')
                try:
                    datetime.datetime.strptime(bldate, '%Y%m%d')
                except ValueError:
                    logger.info(f'Date {bldate} is not formatted YYYYMMDD')
                    raise ValueError
    if not BLDATEFOUND:
        job_obj.comment_append('BL_DATE not found in rt.sh.'
                               'Please manually edit rt.sh '
                               'with BL_DATE={bldate}')
        job_obj.job_failed(logger, 'get_bl_date()')
    logger.info('Finished get_bl_date')

    return bldate


def process_logfile(job_obj, logfile):
    logger = logging.getLogger('BL/PROCESS_LOGFILE')
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
                    logger.info(f'Found "working dir" in line: {line}')
                    rt_dir = os.path.split(line.split()[-1])[0]
                    logger.info(f'It is: {rt_dir}')
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
        raise FileNotFoundError
