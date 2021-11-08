# rrfs-ci
The top level utilities for handling automation of the UFS SRW App and regional_workflow.

The program ci_auto.py is designed to run on an HPC machine. As of November 2021, it is written to run on Hera and/or Jet, and is still being run manually. The configuration file CIrepos.cfg lists the github repositories that have their Pull Requests checked for labels that specify a machine, a compiler, and a test.

The program ci_auto.py requires:
* ConfigParser module to read and write configuration files
* PyGithub module to use the github API
* ufs-srweather-app/test/build.sh
* regional_workflow/tests/WE2E/end_to_end_tests.sh
