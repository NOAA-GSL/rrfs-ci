#!/bin/bash
set -eu

find /scratch2/BMC/zrtrr/rrfs_ci/autoci/tests/auto -type f -name "*.log" -size -400c -delete
find /scratch2/BMC/zrtrr/rrfs_ci/autoci/tests/auto -type f -name "*.log" -mtime +7 -delete

