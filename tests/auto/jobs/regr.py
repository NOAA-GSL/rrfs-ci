"""
Name: regr.py
Python to clone and build a GSI repo and run
regression tests.
"""

# Imports
import datetime
import logging
import time
import os
from configparser import ConfigParser as config_parser


def run(job_obj):
    """
    Runs a regression test for a GSI PR
    """
    logger = logging.getLogger('REGR/RUN')
    pr_repo_loc, repo_dir_str = clone_pr_repo(job_obj, job_obj.workdir)
    # Setting this for local testing
    os.environ['config_path'] = job_obj.workdir
    build_script_loc = pr_repo_loc + '/ush'
    log_name = 'build.out'
    # passing in machine for build
    create_build_commands = [['module purge', pr_repo_loc],
                             [f'module use modulefiles;module load gsi_{job_obj.machine}.{job_obj.compiler}',
                              pr_repo_loc],
                             [f'./build.sh ../ '
                              f' >& {log_name}',
                             build_script_loc]]
    logger.info('Running test build script')
    job_obj.run_commands(logger, create_build_commands)
    # Read the build log to see whether it succeeded
    build_success = post_process(job_obj, build_script_loc, log_name,
                                 pr_repo_loc)
    logger.info('After build post-processing')
    logger.info(f'Action: {job_obj.preq_dict["action"]}')
    # Comments have not yet been written
    issue_id = 0
    if build_success:
        job_obj.comment_append('Build was Successful')
        if job_obj.preq_dict["action"] == 'rt':
            logger.info('Running GSI regression test')
            log_name = 'gsi_ctest.out'
            ctest_loc = pr_repo_loc + '/build/regression'
            create_regr_commands = \
                [[f'ctest --verbose >& '
                  f'{log_name}', ctest_loc]]
            job_obj.run_commands(logger, create_regr_commands)
            logger.info('After GSI regression test')
            ci_log = f'{ctest_loc}/{log_name}'
            error_strings = ['Test #', 'Test  #', 'ed the', 'Thus',
                             'resulting', 'job has']
            if os.path.exists(ci_log):
                with open(ci_log) as fname:
                    for line in fname:
                        if any(x in line for x in error_strings):
                            job_obj.comment_append(f'{line.rstrip().replace("#", "")}')
    else:
        job_obj.comment_append('Build Failed')

    # Only write out comments if not already written after workflow running
    if issue_id == 0:
        issue_id = job_obj.send_comment_text()
        logger.debug(f'Issue comment id is {issue_id}')


def clone_pr_repo(job_obj, workdir):
    ''' clone the GitHub pull request repo, via command line '''
    logger = logging.getLogger('REGR/CLONE_PR_REPO')

    # These are for the new/head repo in the PR
    new_repo = job_obj.preq_dict['preq'].head.repo.full_name
    new_branch = job_obj.preq_dict['preq'].head.ref
    # These are for the default app repo that goes with the workflow
    try:
        auth_repo = job_obj.repo["app_address"]
    except Exception as e:
        logger.info('Error getting app address and branch from config dict')
        job_obj.job_failed(logger, 'clone_pr_repo', exception=e)
    app_name = auth_repo.split("/")[1]
    # The new repo is the default repo
    git_url = f'https://${{ghapitoken}}@github.com/{new_repo}'

    app_branch = new_branch

    logger.info(f'GIT URL: {git_url}')
    logger.info(f'app branch: {app_branch}')
    logger.info('Starting repo clone')
    repo_dir_str = f'{workdir}/pr/'\
                   f'{str(job_obj.preq_dict["preq"].id)}/'\
                   f'{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}'
    pr_repo_loc = f'{repo_dir_str}/{app_name}'
    job_obj.comment_append(f'Repo location: {pr_repo_loc}')

    create_repo_commands = [
        [f'mkdir -p "{repo_dir_str}"', os.getcwd()],
        [f'git clone -b {app_branch} {git_url}', repo_dir_str]]
    job_obj.run_commands(logger, create_repo_commands)

    # copy any extra or revised files needed
    logger.info('Starting file copies')
    create_repo_commands = [[f'cp -r {workdir}/vlab/GSI/fix/* fix/.',
                             pr_repo_loc]]
    job_obj.run_commands(logger, create_repo_commands)

    logger.info('Finished repo clone')
    return pr_repo_loc, repo_dir_str


def post_process(job_obj, build_script_loc, log_name, pr_repo_loc):
    logger = logging.getLogger('REGR/POST_PROCESS')
    ci_log = f'{build_script_loc}/{log_name}'
    gsi_exe = pr_repo_loc + '/install/bin/gsi.x'
    enkf_exe = pr_repo_loc + '/install/bin/enkf.x'
    build_succeeded = False

    if os.path.exists(ci_log):
        # were the executables created?
        if os.path.exists(gsi_exe) and os.path.exists(enkf_exe):
            build_succeeded = True
        if build_succeeded:
            logger.info('Build was successful')
        else:
            logger.info('Build failed')
            job_obj.comment_append('Build failed')
            raise Exception('Build failed abruptly ')

        return build_succeeded
    else:
        logger.critical(f'Could not find {job_obj.machine}'
                        f'.{job_obj.compiler} '
                        f'{job_obj.preq_dict["action"]} log')
        raise FileNotFoundError


def process_gen(job_obj, gen_log_loc, gen_log_name):
    """
    Runs after a rocoto workflow has been generated
    Checks to see if an error has occurred
    """
    logger = logging.getLogger('REGR/PROCESS_GEN')
    gen_log = f'{gen_log_loc}/{gen_log_name}'
    error_string = 'ERROR'
    error_msg = 'err_msg'
    gen_failed = False
    if os.path.exists(gen_log):
        with open(gen_log) as fname:
            for line in fname:
                if error_string in line or error_msg in line:
                    job_obj.comment_append('Generating Workflow Failed')
                    gen_failed = True
                    logger.info('Generating workflow failed')
                if gen_failed:
                    job_obj.comment_append(f'{line.rstrip()}')


def process_expt(job_obj, expts_base_dir):
    """
    Runs after a rocoto workflow has been started to run one or more expts
    Assumes that more expt directories can appear after this job has started
    Checks for success or failure for each expt
    """
    logger = logging.getLogger('REGR/PROCESS_EXPT')
    expt_done = 0
    # wait time for workflow is time_mult * sleep_time seconds
    time_mult = 2
    sleep_time = 6
    repeat_count = time_mult
    complete_expts = []
    expt_list = os.listdir(expts_base_dir)
    complete_string = "This cycle is complete"
    failed_string = "DEAD"

    # Set issue id for cases where workflow does not start
    issue_id = 0

    while (expt_done < len(expt_list)) and repeat_count > 0:
        time.sleep(sleep_time)
        repeat_count = repeat_count - 1
        expt_list = os.listdir(expts_base_dir)
        logger.info('Experiment dir after return of end_to_end')
        logger.info(expt_list)
        for expt in expt_list:
            expt_log = os.path.join(expts_base_dir, expt,
                                    'log/FV3LAM_wflow.log')
            if os.path.exists(expt_log) and expt not in complete_expts:
                with open(expt_log) as fname:
                    for line in fname:
                        if complete_string in line:
                            expt_done = expt_done + 1
                            job_obj.comment_append(f'Experiment done: {expt}')
                            job_obj.comment_append(f'{line.rstrip()}')
                            logger.info(f'Experiment done: {expt}')
                            complete_expts.append(expt)
                        elif failed_string in line:
                            expt_done = expt_done + 1
                            job_obj.comment_append('Experiment failed: '
                                                   f'{expt}')
                            job_obj.comment_append(f'{line.rstrip()}')
                            logger.info(f'Experiment failed: {expt}')
                            complete_expts.append(expt)
    logger.info(f'Wait Cycles completed: {time_mult - repeat_count}')
    logger.info(f'Done: {len(complete_expts)} of {len(expt_list)}')

    # If not all experiments completed, writes a list in a config file
    if len(complete_expts) < len(expt_list):
        job_obj.comment_append(f'Long term tracking will be done'
                               f' on {len(expt_list)} experiments')

        # Write out comments so far and save issue id for later appending
        issue_id = job_obj.send_comment_text()
        logger.debug(f'Issue comment id is {issue_id}')

        undone = list(set(expt_list) - set(complete_expts))
        config = config_parser()
        file_name = 'Longjob.cfg'
        if os.path.exists(file_name):
            config.read(file_name)
        for expt in undone:
            expt_log = os.path.join(expts_base_dir, expt,
                                    'log/FV3LAM_wflow.log')
            logger.info(f'expt log: {expt_log}')
            pr_repo = job_obj.repo["address"]
            pr_num = job_obj.preq_dict['preq'].number
            config[expt_log] = {}
            config[expt_log]['expt'] = expt
            config[expt_log]['machine'] = job_obj.machine
            config[expt_log]['pr_repo'] = pr_repo
            config[expt_log]['pr_num'] = str(pr_num)
            config[expt_log]['issue_id'] = str(issue_id.id)
        with open(file_name, 'w') as fname:
            config.write(fname)

    return issue_id
