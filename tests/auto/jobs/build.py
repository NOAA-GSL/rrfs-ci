# Imports
import datetime
import logging
import os
from configparser import ConfigParser as config_parser


def run(job_obj):
    logger = logging.getLogger('BUILD/RUN')
    workdir = set_directories(job_obj)
    pr_repo_loc, repo_dir_str = clone_pr_repo(job_obj, workdir)
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
        job_obj.comment_text_append('Build was Successful')
        if job_obj.preq_dict["action"] == 'WE':
            logger.info('Running end to end test')
            expt_script_loc = pr_repo_loc + '/regional_workflow/tests/WE2E'
            log_name = 'expt.out'
            create_expt_commands = \
                [[f'./end_to_end_tests.sh {job_obj.machine} zrtrr >& '
                 f'{log_name}', expt_script_loc]]
            job_obj.run_commands(logger, create_expt_commands)
            logger.info('After end_to_end script')
            job_obj.comment_text_append('Rocoto jobs started')
    else:
        job_obj.comment_text_append('Build Failed')
    job_obj.send_comment_text()


def set_directories(job_obj):
    logger = logging.getLogger('BUILD/SET_DIRECTORIES')
    if job_obj.machine == 'hera':
        workdir = '/scratch2/BMC/zrtrr/rrfs_ci/autoci/pr'

    elif job_obj.machine == 'jet':
        workdir = '/lfs4/HFIP/h-nems/emc.nemspara/autort/pr'

    elif job_obj.machine == 'gaea':
        workdir = '/lustre/f2/pdata/ncep/emc.nemspara/autort/pr'

    elif job_obj.machine == 'orion':
        workdir = '/work/noaa/nems/emc.nemspara/autort/pr'

    elif job_obj.machine == 'cheyenne':
        workdir = '/glade/scratch/dtcufsrt/autort/tests/auto/pr'

    else:
        logger.critical(f'Machine {job_obj.machine} id '
                        'not supported for this job')
        raise KeyError

    logger.info(f'machine: {job_obj.machine}')
    logger.info(f'workdir: {workdir}')

    return workdir


def check_for_bl_dir(bldir, job_obj):
    logger = logging.getLogger('BUILD/CHECK_FOR_BL_DIR')
    logger.info('Checking if baseline directory exists')
    if os.path.exists(bldir):
        logger.critical(f'Baseline dir: {bldir} exists. It should not, yet.')
        job_obj.comment_text_append(f'{bldir}\n Exists already. '
                                    'It should not yet. Please delete.')
        raise FileExistsError
    return False


def create_bl_dir(bldir, job_obj):
    logger = logging.getLogger('BUILD/CREATE_BL_DIR')
    if not check_for_bl_dir(bldir, job_obj):
        os.makedirs(bldir)
        if not os.path.exists(bldir):
            logger.critical(f'Someting went wrong creating {bldir}')
            raise FileNotFoundError


def run_regression_test(job_obj, pr_repo_loc):
    logger = logging.getLogger('BUILD/RUN_REGRESSION_TEST')
    if job_obj.compiler == 'gnu':
        rt_command = [[f'export RT_COMPILER="{job_obj.compiler}" && cd tests '
                       '&& /bin/bash --login ./rt.sh -e -c -l rt_gnu.conf',
                       pr_repo_loc]]
    elif job_obj.compiler == 'intel':
        rt_command = [[f'export RT_COMPILER="{job_obj.compiler}" && cd tests '
                       '&& /bin/bash --login ./rt.sh -e -c', pr_repo_loc]]
    job_obj.run_commands(logger, rt_command)


def remove_pr_data(job_obj, pr_repo_loc, repo_dir_str, rt_dir):
    logger = logging.getLogger('BUILD/REMOVE_PR_DATA')
    rm_command = [
                 [f'rm -rf {rt_dir}', pr_repo_loc],
                 [f'rm -rf {repo_dir_str}', pr_repo_loc]
                 ]
    job_obj.run_commands(logger, rm_command)


def clone_pr_repo(job_obj, workdir):
    ''' clone the GitHub pull request repo, via command line '''
    logger = logging.getLogger('BUILD/CLONE_PR_REPO')
    repo_name = job_obj.repo["app_address"]
    branch = job_obj.repo["app_branch"]
    git_url = f'https://${{ghapitoken}}@github.com/{repo_name}'
    logger.info(f'GIT URL: {git_url}')
    logger.info(f'app branch: {branch}')
    logger.info('Starting repo clone')
    repo_dir_str = f'{workdir}/'\
                   f'{str(job_obj.preq_dict["preq"].id)}/'\
                   f'{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}'
    pr_repo_loc = f'{repo_dir_str}/ufs-srweather-app'
    job_obj.comment_text_append(f'Repo location: {pr_repo_loc}')

    create_repo_commands = [
        [f'mkdir -p "{repo_dir_str}"', os.getcwd()],
        [f'git clone -b {branch} {git_url}', repo_dir_str]]
    job_obj.run_commands(logger, create_repo_commands)

    # Set up configparser to read and update Externals.cfg ini/config file
    # to change one repo to match the head of the code in the PR
    config = config_parser()
    file_name = 'Externals.cfg'
    file_path = os.path.join(pr_repo_loc, file_name)
    if not os.path.exists(file_path):
        logger.info('Could not find Externals.cfg')
    else:
        config.read(file_path)
        updated_section = job_obj.preq_dict['preq'].head.repo.name
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
            with open(file_path, 'w') as f:
                config.write(f)
        else:
            logger.info('No section {updated_section} in Externals.cfg')

    # call manage externals with new Externals.cfg to get other repos
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
    logger = logging.getLogger('BUILD/PROCESS_LOGFILE')
    fail_string = 'FAIL'
    build_failed = False
    if os.path.exists(ci_log):
        with open(ci_log) as f:
            for line in f:
                if fail_string in line:
                    build_failed = True
                    job_obj.comment_text_append(f'{line.rstrip()}')
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
