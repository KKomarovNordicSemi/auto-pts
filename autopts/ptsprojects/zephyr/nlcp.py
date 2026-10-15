#
# auto-pts - The Bluetooth PTS Automation Framework
#
# Copyright (c) 2026, Nordic Semiconductor ASA.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms and conditions of the GNU General Public License,
# version 2, as published by the Free Software Foundation.
#
# This program is distributed in the hope it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#

"""NLC Profile Test Suites: ALSNLCP, BLCNLCP, BSSNLCP, DICNLCP, ENMNLCP,
HVINLCP and OCSNLCP.

The module provides the PIXITs and the Test Cases of all seven profiles.
At the end of the file, it is registered under the name of every profile
listed in NLCP_TS_LIST, so the client finds it by the Test Case prefix.
"""


import sys
from fnmatch import fnmatchcase

from autopts.ptsprojects.stack import get_stack
from autopts.ptsprojects.testcase import TestFunc, TestFuncCleanUp
from autopts.ptsprojects.zephyr.nlcp_wid import nlcp_wid_hdl
from autopts.ptsprojects.zephyr.ztestcase import ZTestCase
from autopts.pybtp import btp
from autopts.pybtp.types import BTPError

# Test Suites (profiles) supported by this module.
NLCP_TS_LIST = ("ALSNLCP", "BLCNLCP", "BSSNLCP", "DICNLCP",
                "ENMNLCP", "HVINLCP", "OCSNLCP")

# Set of default PIXITs should be applied for any single Test Case supported here.
NLCP_PROFILE_COMMON_PIXITS = {
    "TSPX_bd_addr_iut": "DEADBEEFDEAD",
    "TSPX_time_guard": "300000",
    "TSPX_use_implicit_send": "TRUE",
    "TSPX_mtu_size": "23",
    "TSPX_delete_link_key": "TRUE",
    "TSPX_delete_ltk": "TRUE",
    "TSPX_security_enabled": "FALSE",
    "TSPX_iut_setup_att_over_br_edr": "FALSE",
    "TSPX_scan_interval": "30",
    "TSPX_scan_window": "30",
    "TSPX_scan_filter": "00",
    "TSPX_advertising_interval_min": "160",
    "TSPX_advertising_interval_max": "160",
    "TSPX_tester_OOB_information": "F87F",
    "TSPX_device_uuid2": "00000000000000000000000000000000",
    "TSPX_use_pb_gatt_bearer": "TRUE",
    "TSPX_iut_comp_data_page": "2",
    "TSPX_oob_state_change": "FALSE",
}
# Per-profile PIXIT overrides, merged over the common ones.
# Pattern here: {"<NLC_PROFILE>": {"TSPX_...": "..."}}
NLCP_PROFILE_EXTRA_PIXITS = {}

# Default Auto-PTS timeout duration for the Client, in ms.
NLCP_TC_COMMON_CLI_TIMEOUT_MS = 300000
# Timeout duration for Performance based Test Cases, in ms.
NLCP_TC_PERF_CLI_TIMEOUT_MS = 900000


def _nlcp_pixit_update_store_keys(pts, profile, need_store):
    state = "FALSE" if need_store else "TRUE"
    for name in ("TSPX_delete_link_key", "TSPX_delete_ltk"):
        pts.update_pixit_param(profile, name, state)


def _nlcp_pixit_update_identity(pts, profile):
    nlcp = get_stack().nlcp
    pts.update_pixit_param(profile, "TSPX_device_uuid", nlcp.get_identity_uuid())


def _nlcp_get_profiles(pts):
    profiles_list = pts.get_project_list()
    return [profile for profile in NLCP_TS_LIST if profile in profiles_list]


def _nlcp_get_cli_default_timeout_ms():
    client = sys.modules.get("autopts.client")
    return getattr(client, "TEST_CASE_TIMEOUT_MS", NLCP_TC_COMMON_CLI_TIMEOUT_MS)


def _nlcp_preconditions_default(pts, profile, stack):
    """Default Test Case: reset the IUT and pass its UUID to the PTS."""
    return [
        TestFunc(stack.nlcp_init),
        TestFunc(_nlcp_tc_reset_node),
        TestFunc(btp.nlcp_read_identity_report),
        TestFunc(lambda: _nlcp_pixit_update_identity(pts, profile)),
    ]


def _nlcp_preconditions_preprovisioned(pts, profile, stack):
    """Preprovisioned Test Case: IUT might be preprovisioned within previous
    Test Case, so make no reset, keys are kept.
    """
    return [
        TestFunc(stack.nlcp_init),
        *_nlcp_tc_keep_keys(pts, profile),
        TestFunc(btp.nlcp_read_identity_report),
        TestFunc(lambda: _nlcp_pixit_update_identity(pts, profile)),
    ]


def _nlcp_preconditions_performance(pts, profile, stack):
    """Performance Test Case: special preconditions for */PERF/* Test Cases,
    based on the default ones with the extended client timeout.
    """
    return (_nlcp_preconditions_default(pts, profile, stack) +
            _nlcp_tc_launch(pts, NLCP_TC_PERF_CLI_TIMEOUT_MS))


# Test Cases with preconditions different from _nlcp_preconditions_default().
# Each entry is a Test Case name pattern and the function with its preconditions.
# The first matching pattern is used.
# To add a new case, write a _nlcp_preconditions_*() function and add it here,
# e.g. ("BSSNLCP/*", _nlcp_preconditions_bss).
NLCP_TC_PRECONDITIONS = (
    ("*/GMIT/PERF/*", _nlcp_preconditions_performance),
    ("*/SPEC/PROP/*", _nlcp_preconditions_preprovisioned),
)


def _nlcp_preconditions_build(pts, profile, stack, tc_name):
    """Return new steps for the Test Case. Steps can not be shared between Test
    Cases.
    """
    for pattern, build in NLCP_TC_PRECONDITIONS:
        if fnmatchcase(tc_name, pattern):
            return build(pts, profile, stack)
    return _nlcp_preconditions_default(pts, profile, stack)


def _nlcp_tc_launch(pts, timeout_ms):
    """Set a longer PTS timeout for this Test Case.

    The timeout is set back to default after the Test Case, even if it fails.
    """
    return [
        TestFunc(lambda: pts.set_call_timeout(timeout_ms)),
        TestFuncCleanUp(lambda: pts.set_call_timeout(_nlcp_get_cli_default_timeout_ms())),
    ]


def _nlcp_tc_keep_keys(pts, profile):
    """Keep the PTS keys for this Test Case.

    Works only if the PTS has provisioned the IUT before, in this session.
    Otherwise, the Test Case fails with BTP ERROR.
    After the Test Case, the PIXITs are set back to default.
    """
    def _process():
        if not get_stack().nlcp.has_been_provisioned_by_lt:
            raise BTPError(f"{profile}: is not provisioned within this session")
        _nlcp_pixit_update_store_keys(pts, profile, need_store=True)

    return [
        TestFunc(_process),
        TestFuncCleanUp(lambda: _nlcp_pixit_update_store_keys(pts, profile, need_store=False)),
    ]


def _nlcp_tc_reset_node():
    """Reset the IUT before the Test Case."""
    btp.nlcp_process_node_reset()
    get_stack().nlcp.has_been_provisioned_by_lt = False


def set_pixits(ptses):
    """Setup NLC Profiles PIXITS for workspace.
    Those values are used for test case if not updated within test case.

    PIXITS always should be updated accordingly to project and newest version of
    PTS.

    ptses -- list of PyPTS instances"""

    pts = ptses[0]

    for profile in _nlcp_get_profiles(pts):
        pixits = {**NLCP_PROFILE_COMMON_PIXITS, **NLCP_PROFILE_EXTRA_PIXITS.get(profile, {})}
        for name, value in pixits.items():
            pts.set_pixit(profile, name, value)


def test_cases(ptses):
    """
    Returns a list of NLCP profiles test cases.

    ptses -- list of PyPTS instances
    """

    pts = ptses[0]
    stack = get_stack()

    tc_list = []

    # Cycle all of the supported Profiles.
    for profile in _nlcp_get_profiles(pts):
        # Build a list of the Test Cases available for the profile.
        tc_list.extend(
            ZTestCase(profile, tc_name,
                      cmds=_nlcp_preconditions_build(pts, profile, stack, tc_name),
                      generic_wid_hdl=nlcp_wid_hdl)
            for tc_name in pts.get_test_case_list(profile)
        )

    return tc_list


# Register this module under the name of every NLC profile, so the client
# lookup by the test case prefix (e.g. HVINLCP -> hvinlcp) finds this file.
_this = sys.modules[__name__]
_pkg = sys.modules[__package__]
for _p in NLCP_TS_LIST:
    _alias = _p.lower()
    setattr(_pkg, _alias, _this)                      # getattr(zephyr, 'hvinlcp')
    sys.modules[f"{__package__}.{_alias}"] = _this    # import_module('...zephyr.hvinlcp')
