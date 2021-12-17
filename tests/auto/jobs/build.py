"""
Name: build.py
Python to clone and build a repo and if requested run
End to End workflow tests.
"""

# Imports
import datetime
import logging
import time
import os
from configparser import ConfigParser as config_parser


def run(job_obj):
    """
    Runs a CI test for a PR
    """
    logger = logging.getLogger('BUILD/RUN')
    pr_repo_loc, repo_dir_str = clone_pr_repo(job_obj, job_obj.workdir)
    # Setting this for the test/build.sh script
    os.environ['SR_WX_APP_TOP_DIR'] = pr_repo_loc
    build_script_loc = pr_repo_loc + '/test'
    log_name = 'build.out'
    create_build_commands = [[f'./build.sh {job_obj.machine} >& {log_name}',
                             build_script_loc]]
    logger.info('Running test build script')
    job_obj.run_commands(logger, create_build_commands)
    # Read the build log to see whether it succeeded
    build_success = post_process(job_obj, build_script_loc, log_name)
    logger.info('After build post-processing')
    logger.info(f'Action: {job_obj.preq_dict["action"]}')
    if build_success:
        job_obj.comment_append('Build was Successful')
        if job_obj.preq_dict["action"] == 'WE':
            expt_script_loc = pr_repo_loc + '/regional_workflow/tests/WE2E'
            expts_base_dir = os.path.join(repo_dir_str, 'expt_dirs')
            log_name = 'expt.out'
            we2e_script = expt_script_loc + '/end_to_end_tests.sh'
            if os.path.exists(we2e_script):
                logger.info('Running end to end test')
                create_expt_commands = \
                    [[f'./end_to_end_tests.sh {job_obj.machine} '
                      f'{job_obj.hpc_acc} >& '
                      f'{log_name}', expt_script_loc]]
                job_obj.run_commands(logger, create_expt_commands)
                logger.info('After end_to_end script')
                # no experiment dir or no test dirs in it suggests error
                if os.path.exists(expts_base_dir) and \
                   len(os.listdir(expts_base_dir)):
                    job_obj.comment_append('Rocoto jobs started')
                    process_expt(job_obj, expts_base_dir)
                else:
                    gen_log_loc = pr_repo_loc + '/regional_workflow/ush'
                    gen_log_name = 'log.generate_FV3LAM_wflow'
                    process_gen(job_obj, gen_log_loc, gen_log_name)
            else:
                job_obj.comment_append(f'Script {we2e_script} '
                                       'does not exist in repo')
                job_obj.comment_append('Cannot run WE2E tests')
    else:
        job_obj.comment_append('Build Failed')
    job_obj.send_comment_text()


def clone_pr_repo(job_obj, workdir):
    ''' clone the GitHub pull request repo, via command line '''
    logger = logging.getLogger('BUILD/CLONE_PR_REPO')

    # These are for the new/head repo in the PR
    new_name = job_obj.preq_dict['preq'].head.repo.name
    new_repo = job_obj.preq_dict['preq'].head.repo.full_name
    new_branch = job_obj.preq_dict['preq'].head.ref
    # These are for the default app repo that goes with the workflow
    try:
        auth_repo = job_obj.repo["app_address"]
        auth_branch = job_obj.repo["app_branch"]
    except Exception as e:
        logger.info('Error getting app address and branch from config dict')
        job_obj.job_failed(logger, 'clone_pr_repo', exception=e)
    app_name = auth_repo.split("/")[1]
    # The new repo is the default repo
    git_url = f'https://${{ghapitoken}}@github.com/{new_repo}'

    # If the new repo is the regional workflow (not the app)
    if new_name != app_name:
        # look for a matching app repo/branch
        app_repo = os.path.join(job_obj.preq_dict['preq'].head.user.login,
                                app_name)
        branch_list = list(job_obj.ghinterface_obj.client.get_repo(app_repo)
                           .get_branches())
        if new_branch in [branch.name for branch in branch_list]:
            git_url = f'https://${{ghapitoken}}@github.com/{app_repo}'
            app_branch = new_branch
        else:
            git_url = f'https://${{ghapitoken}}@github.com/{auth_repo}'
            app_branch = auth_branch
    else:
        app_branch = new_branch

    logger.info(f'GIT URL: {git_url}')
    logger.info(f'app branch: {app_branch}')
    logger.info('Starting repo clone')
    repo_dir_str = f'{workdir}/'\
                   f'{str(job_obj.preq_dict["preq"].id)}/'\
                   f'{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}'
    pr_repo_loc = f'{repo_dir_str}/{app_name}'
    job_obj.comment_append(f'Repo location: {pr_repo_loc}')

    create_repo_commands = [
        [f'mkdir -p "{repo_dir_str}"', os.getcwd()],
        [f'git clone -b {app_branch} {git_url}', repo_dir_str]]
    job_obj.run_commands(logger, create_repo_commands)

    # Set up configparser to read and update Externals.cfg ini/config file
    # to change one repo to match the head of the code in the PR
    config = config_parser()
    file_name = 'Externals.cfg'
    file_path = os.path.join(pr_repo_loc, file_name)

    if not os.path.exists(file_path):
        logger.info(f'Could not find {file_path}')
        raise FileNotFoundError

    # Only update Externals.cfg for a PR on a regional workflow
    if new_name != app_name:
        config.read(file_path)
        updated_section = new_name
        logger.info(f'updated section: {updated_section}')
        new_repo = "https://github.com/" + \
            job_obj.preq_dict['preq'].head.repo.full_name
        logger.info(f'new repo: {new_repo}')

        if config.has_section(updated_section):

            config.set(updated_section, 'hash',
                       job_obj.preq_dict['preq'].head.sha)
            config.set(updated_section, 'repo_url', new_repo)
            # Can only have one of hash, branch, tag
            if config.has_option(updated_section, 'branch'):
                config.remove_option(updated_section, 'branch')
            if config.has_option(updated_section, 'tag'):
                config.remove_option(updated_section, 'tag')
            # open existing Externals.cfg to update it
            with open(file_path, 'w') as fname:
                config.write(fname)
        else:
            logger.info('No section {updated_section} in Externals.cfg')

    # call manage externals to get other repos
    logger.info('Starting manage externals')
    create_repo_commands = [['./manage_externals/checkout_externals',
                             pr_repo_loc]]

    job_obj.run_commands(logger, create_repo_commands)

    logger.info('Finished repo clone')
    return pr_repo_loc, repo_dir_str


def post_process(job_obj, build_script_loc, log_name):
    logger = logging.getLogger('BUILD/POST_PROCESS')
    ci_log = f'{build_script_loc}/{log_name}'
    logfile_pass = process_logfile(job_obj, ci_log)
    logger.info('Log file was processed')
    logger.info(f'Status of build: {logfile_pass}')

    return logfile_pass


def process_logfile(job_obj, ci_log):
    """
    Runs after code has been cloned and built
    Checks to see whether build was successful or failed
    """
    logger = logging.getLogger('BUILD/PROCESS_LOGFILE')
    fail_string = 'FAIL'
    build_failed = False
    if os.path.exists(ci_log):
        with open(ci_log) as fname:
            for line in fname:
                if fail_string in line:
                    build_failed = True
                    job_obj.comment_append(f'{line.rstrip()}')
        if build_failed:
            job_obj.send_comment_text()
            logger.info('Build failed')
        else:
            logger.info('Build was successful')
        return not build_failed
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
    logger = logging.getLogger('BUILD/PROCESS_GEN')
    gen_log = f'{gen_log_loc}/{gen_log_name}'
    error_string = 'ERROR'
    gen_failed = False
    if os.path.exists(gen_log):
        with open(gen_log) as fname:
            for line in fname:
                if error_string in line:
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
    logger = logging.getLogger('BUILD/PROCESS_EXPT')
    expt_done = 0
    # wait time for workflow is time_mult * sleep_time seconds
    time_mult = 2
    sleep_time = 6
    repeat_count = time_mult
    complete_expts = []
    expt_list = os.listdir(expts_base_dir)
    complete_string = "This cycle is complete"
    failed_string = "FAILED"

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
                        else:
                            if failed_string in line:
                                expt_done = expt_done + 1
                                job_obj.comment_append('Experiment failed: '
                                                       f'{expt}')
                                job_obj.comment_append(f'{line.rstrip()}')
                                logger.info(f'Experiment failed: {expt}')
                                complete_expts.append(expt)
    logger.info(f'Wait Cycles completed: {time_mult - repeat_count}')
    job_obj.comment_append(f'Done: {len(complete_expts)} of {len(expt_list)}')

    # If not all experiments completed, writes a list in a config file
    if len(complete_expts) < len(expt_list):
        job_obj.comment_append('Long term tracking will be done')
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
            config[expt_log]['pr_repo'] = pr_repo
            config[expt_log]['pr_num'] = str(pr_num)
        with open(file_name, 'w') as fname:
            config.write(fname)
