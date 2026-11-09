#!/usr/bin/env python3
"""Offline adversarial manual pinning tests; no specialist/provider/state writes."""
from __future__ import annotations

import ast
import base64
import copy
import contextlib
import gzip
import hashlib
import io
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import manual_foundation as manual
from tools import run_pr_validation as registered_validation

BASE = '11163fb3e30125359346102eb2b12c04aa52ae15'
REVIEW_HEAD = 'a' * 40
MOVED_REVIEW_HEAD = 'b' * 40


def historical_catalog_fixture_bytes(raw, expected_sha):
    """Recover reviewed Git-LF bytes only inside a historical test fixture.

    Windows checkout conversion is harmless only when reversing CRLF yields
    the exact original catalog hash. Any content change remains uncorrected
    so the unchanged production hash guard can refuse it.
    """
    canonical = raw.replace(b'\r\n', b'\n')
    return canonical if hashlib.sha256(canonical).hexdigest() == expected_sha else raw


def independent_hash(value, excluded):
    return hashlib.sha256(json.dumps({k: v for k, v in value.items() if k != excluded},
        sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def fixture_dependency_bytes(name, source_commit):
    if name in (HISTORICAL_LAKE_FIXTURE, HISTORICAL_SEC_FIXTURE, HISTORICAL_A3_FIXTURE):
        return _historical_lake_archive_bytes(source_commit, name)
    source = ROOT / name
    if source.is_symlink():
        raise FileNotFoundError(str(source))
    try:
        return source.read_bytes()
    except FileNotFoundError:
        entry = subprocess.check_output(['git', 'ls-tree', '-z', source_commit, '--', name],
                                        cwd=ROOT, stderr=subprocess.PIPE)
        metadata, separator, path = entry.rstrip(b'\0').partition(b'\t')
        fields = metadata.split()
        if (not separator or path != name.encode() or len(fields) != 3 or
                fields[0] not in (b'100644', b'100755') or fields[1] != b'blob'):
            raise
        return subprocess.check_output(['git', 'cat-file', 'blob', fields[2].decode()],
                                       cwd=ROOT, stderr=subprocess.PIPE)


HISTORICAL_LAKE_FIXTURE = 'tests/fixtures/manual_foundation_long_history_lake_v1.py.gz'
HISTORICAL_LAKE_SHA256 = 'fc1cddbdaa9f96241f5a058a6398027751dec3b86ac78e2b164fe4064bda3b8c'

# Immutable historical test inputs, not current-source reuse certification.
# These exact Git-LF bytes are bound by the unchanged historical catalog.
HISTORICAL_READER_INPUTS = {
    'tools/macro_history_sources.py': ('84a958b3c6aaf6e6e6c3133eceed8326aff768f1f24ca050fa3fa06b54f281c8', 20361,
        b'H4sIAAAAAAACCs08/XPbtpK/66/AY+bmyIT6sF/a3rnlu1EdpfXUjf1k5/VanYZDi5DFmiJVgrSjZvK/3+4CIAGSUtzeu5vztLFE'
        b'AIvFYr936Rd/GVeiGN8l2Zhnj2y3Lzd59teB4zjf5lUW85i9nc/ejKeX+IsVXPCoWG3YKk9TviqTPPuaJdttVUZ3KWdF9MTyu19h'
        b'QPgsy1lZRHGS3TNRRiUfDQbfFdFuwzaJKPNizxLBVlVR8KwM8yzdj1i9SZQOy2TLWQzLBIsK+WmY8keeMtw/eeQD/pjEPFtxn0Xx'
        b'NilLQBXBsGhd8oKVm6hk7/gT+zkvHmg541mMaAGQgkWCJRmiF+3hyZMYDW433DgVILHiya5EJLO8ZHozlq9haJsDuB0vBJxEPi3Y'
        b'9cUt2xXJigMsoN5gXeRbFobrqqwKHoZApV1elCzKAFyEW4jBQD8r7ndRIbj+vhKPcjmiTYRQA/jdr5/6rPk35mkZyY+/51kNaROJ'
        b'TZrc6a9Jrj/9KvJMf95G5UZ/zoXceQfPYKHe+NqYUnA5pSpSmDHiRQGnV2Pf395ez/CBz97PL+mTNZmOqSfDMyBeHtvwCv5bxUVp'
        b'QpzzOIH7KL+PsjjlAHsu5/jsrkrSOMx3PONqIzx9kq1zvf4X+H4B3weD+dXVLQvoKC7cS5LCrXiwncjTR+56iBuwolicLAfz2XcX'
        b'N7fzn2E6rRozJ85XYryNVkUeJlmcrCJg4bDg98ABxX6E5HQGP07/M/z259vZDaw7+ZK9ZCeT09fqFw1eT7+jwdPJQPI6PQlvLn6Z'
        b'wdMvJuFkUo/g/PnVTzi9WfqStdcNrt9/e3lxHs7m86s5TgYq/M4zwUv3o7MueBw+8H1YZdFjlKQopI7PnCilkbwqd1UZrnKUhFVp'
        b'jOyiex7m6zWAcfwBgx89sgKtYM6k7+FqE2X3PDae8+2u3BMc4yFybniHekW0wMbVLkWi8vAR5NJelQCTbHcph0GAl2QkPeYxQKDT'
        b'aLcDTaNXt8HTedIE1ASuu0c1FIrVhm+j5nuRP+GXBhO4YCW9+Z3gxaPaVwLO8mydZAkiHKUVoSuPDDMT3J85Iq+KVXNe5hhgwifg'
        b'ItxQQlsBksB8SZSGfLXJgbFQiUqCFor7Ww/FDlQID0XyO3c+eYPBIOaomn6rYLILVxonuI+P2hSY0zujjZI1abN6WD7FnyJKQDL/'
        b'gWchsXXVOgW4Kldhlj+5Ck7BgS5ZrYlGOKR1zwjmeqNE5Ou8ANXiahBgBLY7l6hVQxFVWgLP1nBQhJuVNBckdJdGK+46v+DBX00m'
        b'Z5OJ43kKgjyvhDQqf5eiL3X2O0AGVmi8QjU5djzzDGppJPQ8+yAKeamo4hb6BMBF4R/F1XYn5LDPBGgelDsR3Bb4HeQR2SgSqyQJ'
        b'3kapQKOVpvlTmEWZelDfROtHcFBMqG1E4Do+kuAMTs9eMee/MscbScRqIscJMH/pgiG2kVSGYCQ20ekXX9L4aMM/qOn1KT+s0kqA'
        b'cXVR//usAQMW7acCuB1M7IqP2OwD6D207Amx7SpKtd0naw1PQfuCaSy/Rl5bg0DByBo00AhNIwLEDbQ2xs/2feL1Rdne3QEfhWK/'
        b'TZPswfUY8AXbgeFmC4nfS/ylFffSQ5mTc0McUPdszBltH0CWXLVAXw6eJcwf6KtcAiq9kYynBDAlIGhnXOfDneOh/7Aha3Rm3Zt8'
        b'NnpCUhGRaRTIysGVeAsmhwgnSMIM2VOnpk1A7uLwbg+ODxw4CPAO4Fy1j0UnCzVRnUbwpSVqCSixZppHsXC1TbM20MuzanvHC4u7'
        b'QVXQVyS364yQ8eB/lCnPxJy2wae2RK9hUyXA9s2iswGXKnWnklu8uLY+7ZFRhSv5ECHpbJeIIzWujwqmAJ+g3BR5dY/cy0sYeOSx'
        b'QnidFOgzpCDqSue09A0B8Py+IQXUPgsBZN8EEiT8liqu2XeEkFyvX/VrWFEM/miATt/oDVzpnB64ST66ATDZ/cUVnnIUc5JzpyrX'
        b'w38biuQelEBbB+LC0TrhaZxFWy7o5hbW1oiPoym29NnCeTO9nTVPvLZ1lFsIzsmSrPICXWigi0DhhwODmwFrFghqKYkMIgqWFPeW'
        b'CHXZHBfBFOJu+txG3LNsslcDQGe99+Jg2qIDZTFZLr3O5uTwg3YB/PBUoGVigqtu8RkOQAMTAYyiOEagzdMXFDGBV73X7BthrJDk'
        b'MWwGxr1gdxzwxmhDxCN2UccYEcxPwepCpKRhgRAScpJ3bV2DbluSVbx+KMU10MKMRNHXagJUUi1Iam2Q6mJH4ExBsITHMu24d3x7'
        b'xR71YuBlV+4faAlts2LQ2sGXyAXSjB6yiPRT+7NhVAa1xPlsV92lidiAzwfPpQegfEK5Iz06ClmHeoFjRqeOoU+sLVtSeJfnqatI'
        b'4bWdwpZSs8XJUm/Sb3XRbxXP13BgXK8pwtIOM1Mufrnf8eCEEbiv2QPnO4ZhMHLoYyIw3kU5QEsXg7KJGjP9/1JnttQR/7Ajv1gF'
        b'LEAfiLBTWztN/MZIkYqKSEURQRoZ2EV7NJaw1DCctRm3TTXNHN3DFk4FdgsuF/WZA96HQ8S0ZhjXIOeddHnwUFT2mc1VlEZQO5To'
        b'i+caeBS7wWEteDLA624KbJLBXYFguDTFxwSKR0edgIKSsOA+W+FrK1LsASxvS+kjzKQotAJ5j4dCzQaQvm4ab8DnT6J9NoOjMCBb'
        b'LI8eEyEA64NfJY8pRRseer1hbgPLtIEw3daxR42YQwZ6aWtapb+OrMKMGUYtIUljez1o4+eshWntldK7LxFhNAa1KrVndUTbsKem'
        b'fdXnMIcQt7/VQ/2KuS970I9Bja9h4f0jOQYbSm3ONRh7+AUwqLbQTGbl0MVaczASMaPkU8S2ILWbIV2Dae3gwHc8HQ16LZgZAIPi'
        b'vksgBtW0etVk9/AGRHDiySwfKLajVsz60Ukw15luwZSsovE7/hRiZhS8yMOhr03i/7l17yAsrb3hrzjS+Uc/1LLa6stxaCYnB/C/'
        b'7VlYDkP95TjEHmei8Q5MrlQ56c85CTIYtHQ0ewXSAGEl6ZVBVy8e0+r9iTEJ5QW7atJiqKrxalLBnvIqjWXygZVPubwCAToUvFKI'
        b'e8EzjIBzQRFDwEGegWTaO1By0ocN2MdPjRklriBRywtA0a2N8gPfB2m0vYvBqz1jbtETh4BZhsfmPcPFG8HlDp2TvEItXm9Pelxu'
        b'0gexx1ZqIIaBqZ99wzQoG4vP5BabXWq8FodxWgL+etRWtj3eIDiBK1COiKvOers9KXBFJRn51+lBSoqDVKZrn72Minu4hpcvH57w'
        b'k3ck09eTYTTziQBTpQuqAqzxS3RHV4B1YOQCKEdiJuNdA39QMZQ5UVl7CWZD4ZoIPtZ4Oe+BcsPpPehe54w5lGsfanEb6srT+GQ0'
        b'wVzEdIU5FZwIt0NqHSg+RrfNL/mHcgzhtPNJ6UrwqILTCSVtdN60G5XqkREWq5DpME0PbqOzK3JEogjlgOnBgBMZ1CApseI2NYBX'
        b'7MQWaHSTSNTBoUQjWE/t5HO7yTBJcmRe+anO+2lTJ9NEB/PIduQRPan7XfNytXEPhRdb2KHJBuE3cnFVWOQ0NIQbBUI4m7LcibPx'
        b'GCUHyJjmVSLW8DEv7scUz9MIfRrB/fyHAzSqi0Cu7SWhfUni2rZgrBwo/FY5jwMdXHjtXNSiw7MeyHOdv6bpoJwA31wAFR+TAnQc'
        b'eYfkt06vL8IfZj87PVEdrELPr7eoolONFK4pzR7IyKNWlqG8J/Be3bqi4x0kYrRL2jTEnceSImPTlW0RkmjX8mxwTWjQE6DjGQL4'
        b'32dUC6MQ0aFCFpALI5qAghnfjiFtI2lqO7odfUfmAJpjI2Q1XdXAOfnqqy+Hk6+Gk9eOPzhozevlVMMJ2kUwTfJA/vK6ItpRY0qH'
        b'4Z0a+aUyOhL76XAJp/0fx0rEWNr3sgNSGeY0OD0jxnl2IHPIRVEaQfN5D0nOWndJoqnEw5ZFEzEF8JsOPBAjr586XWvWLflpayZN'
        b'dXgf7UTjqKyJObLVXttU8LIxdyD9mY+9jov0fWSOk8AgNYraezULUJ88rT/rjdhfQMwpUEj3zuFcOs1AVD4C87jx4uz10nt5cgqi'
        b'Lr9/cfbV0mNDdkLYkBOGuH8yNf1i7XzMxuOT07PJ6/jT8GP2Lyenr07OJqfxJ4eWZY1O2iaZK/cEUm+jD/rLqxOP6oba0sjHS2kS'
        b'CEWewhUslorKqonCxSYP7je654CBqdNscMlkjngR0G91Hy/YNWxabjgTEcRcutDBSJZZJTD2IrOoOzdQyuruDRXJjRQobAiRCLFt'
        b'BSEoHmkbPYDTm6L13g83HLzjuwqdLACe4UMK0WRTSUTVrOReQat2siEDtgcnHKO/JB4WVdYgCS4QNkwMKfyThyA8OV4XKFUxUrcl'
        b'54dSXfWWamTmCyIBYgmxcBLwIM+YkKfHizH1lgHQWzgq/bj8ZJdi0KBTdae5ASU9TqOsUPKbOyTH5TW6RU2vTChW+a7ttLSXBYGC'
        b'VJqP5Tath5QVxEd4WBT7KnsAfZG1s6g6oX8gJykzEQezkk3usdZHRu7ROJ2dekSm1nVL+uLZN4iFVtTHqg5r3oOuBaoSqwQ1xjwn'
        b'VU4d+GyB8Vl3eVLyrSDPonYrFD9TukPTsNEqVinT8FHq0BSLdVLsjvuBvQkXzSAEtHZqZa8K3izEmc0c2+ltirlycadhopWKOuqA'
        b'tvEycKJkq64nkVFoG9dWisOsb5m1RoK3mCyfk46382+p4GeHdqs3+aMZ/w7ABuvFnzVaaHuWrYK22HBiOKOzoJNBt9eoUUB+E+GU'
        b'35OdPpYE53WpcVwsAJBsRmhlUsld060ZuujSmdOSSXzUuqCjm9cgqMjRWorySKC76TAZLgbO+dXl5ez8dvbGqWsWoWzDCBrQXfaI'
        b'nvQsSTTsKiHxqIokOBpqqQjBeaUw6cIGRy4gj66uU5nsIt0kOeOZ/s+nnuQZhOspbF8G6Fg8D0xfCk5H31INq7ABQT6Ty5evlGD0'
        b'AFcjYRsMXKJ0/9AM6eU961OcC9iAs/TcAx5IEPaQTyca1VLQPAtHP8QUlUae5FcqNbqyw8elLGAWpaFeKv23oNcvJuurC8gLp/Ze'
        b'MUfXEYE6NsEvZq6TGl/qrlDMwMCzs8PrjwnSt5dX5z8oMcLetMBBwCHweVm4AHaEesDzOtu7uhXVZ7cyG6S+Xd3QB++fhs/tfPru'
        b'5vpqfhtezcOb26v5TPZlOj1INSELoAWhtfr4A9/rBtoswQOpb9geIrHtJeILNi3ukrKI0OmkHdAV3nIhUPGSLZ5eX2BTruH5cuQH'
        b'QB4bZcWoHX3DiTAOkrSlEKD5nDG77ZQiAOfm6v38fBaeX70DQpwTETCV8k+irmpI1P6WdPC16qVulUAlDVWD+VD68cPHE0eFGviP'
        b'r7MBIIFmysIKRuWwsrpN9mEFOJRScmun0fDSlL62nbimW4TUtwiIAmBLqoKqEbKbPHyE468THuv2QHkG7KwLqas83CVla5IOgJ9s'
        b'I4h08cweu9qoqUGyaq5hz185soG57aE2TYCtTDVC8Qm8ivkw6ggluXXcp6aFqlPPdmbN3LHjONjzRNGRWvSvyOHRqmwCqUdstsd2'
        b'VtW+j037knexN3SLvX0DgoYRno7fAOFIxo5J0YAC8aE4DtsTh1EcFyAk+O4AWfwR+74mvCp8lFx1Mgnq6RHVbpfuIeZLsOKStgNS'
        b'/gGz0UmJ7zPgKwVAnQh716jiB/P3Al97AL8YsBdlkqbaZ4Wlv1VRitVLyqYjOZSjW++BPgCLCJYqgzdZhTHm7MYyPoUNMsoaJ2AQ'
        b'ABUAQLp/hznkKGN5HeRKqZ8CPYqiAnmiy4OILANbsMmpNanga4yyNekVyQHAvsaPji5B3W4SqrXgozEab55hHgzrTEkcyZZkRO2G'
        b'pGGMb02AXQCjk0GQtqJXOURTdtJtKJLJKegy+crrRsg6AuiZK8hXC8weWb8WChJWp61c+lKBTcGAZkF0LVvllhSbHNZA9U5Wa50u'
        b'7skikQTYUih1oaiTXNSLUWsWnsp8jNZVmkKku9q4zmIy/PdouF5+/PL1J6fplPGsFmlLPzeb69yJjnw1S1jBb8tX1hvonJeV2Oi0'
        b'nD077VGXRMFO2jG1ZjVh5SvsKWbUaVfgsTehJ1A3i66+QRG79QQNoqLJiHqIheu1uobrcdk5XKjOYQDGo61twJXgBWrwYDHJSn1I'
        b'3OXSg1hrJEwOV+q0xeGdbIPeSE2XGVnNvga712/EDDUMZPkOrQ3OtSGqvI5qtrGQN2VFPuWSTh+pXwCTYGa/jYJ7KOXVMAfXJMNH'
        b'nVUWDk3fSCsBpT1l7CPFsrgvO86azAzpOOX+K10hnQBn2dMWS0MNDnJdfWJKlLWnmH0u3YayhooycjTzdFbDSxuuleWvB2X5c0np'
        b'6yao/UxTap1A0GCawBZAvWKL+rkVGjvLpdVOpVIJEtpZby7qqOaD9V7rvRCpttpqrpVccA1dN6413RjBddXUAfmkrAE1O2MaQ+9r'
        b'SKPBTYv2VSxtGW0yEG1vrGkgoPd1KDUdgqnO3EiE+dqvux583cQUgj3PStG4YdNVCR6I9HDAy6ybnaTUloLFBbiF4Lly9pQXD18b'
        b'JY26hZkyrtpsr6oyX6+ZTrQSInYiu3lvoTmy/SaBmemERcTuuLhhAkoO40y5C/GSPGCEvXC0VEmheW7kbVOW8IIAsNQpDfep1ldN'
        b'PdJYzTyjVkbRv1LhiAcuRFSacB+RgU0JIkVMda2HOI6at/GtF6oNKtqh2Ls1bKOJpWR/q/eUZyRVQMQwWhGpfx2JU7bmICYIQ+7T'
        b'nFe3PzDn2+n5D28vLi/D+ezv7y/mIOv6/bHmBHad2ZnPLmfTm1n45v2MJuOZZGz40/TiNlTDNKQwk6Pn08vZuzfTOcx4O5/dfN9s'
        b'aUqIfFGrJ3Ssr6MOH+UvWydm/AO2uGjWoCSSxMJ6Xa2NXNdHwuN3ckYBPpX2TKaFnJ7Lbpe4JS66iyuDSCRw1NFvwjqc/sdsjpXu'
        b'8+9n5z+0quQQSQA1oiKsilTRwXxEPVaqxVv3Mqlp7ccwtYUcx8wSHTBwqP4VUr5SekEhMGYI9MK3I6i6JVqYYaydhkaAFtCWELbF'
        b'CAICIIBSyN567/DbPlSbCPWZ3MPVxEaNvcUlWJyGOIwCNKnFNAzxtXybnF4WR/8irjBYhJvDV9aTDJUDiBq1Y2pF1q67NUW3PgVm'
        b'+xx91S0Ch6J9sLqmL7GvtjbBae6R2tbwYFEMS1x7Ibex9rGqXP9b/TFS8dYGSKgWGaOh8Hgx64+1yKhdPttm9Ae7Y4xc3paXUU/T'
        b'yNFuE1OhSfFXLRwamCS2JtGBFg7pyDbr6zqXOowe6/FumiGyvw0MyjAnui/xUFN8vdpoajFA/g1ftXCaB47lSxoTdd+aOqft0z3z'
        b'otXiMeXsP9sFZR8+ME/ymXaoVtNSK2F4vGMpyVZpFfP6RgjXEMPDMMtJowYO9t06urnpZDKZtFLs/e+lPJPNzGPLP6jReivCGmzx'
        b'28HXTlQRVUdQFgzUAkZvstYxTi9OYtFcxNLgSILU+0pFz7oDEYF8v6FmRfLxzGtv1N/BKOCPvqzxzLaE/We6E0zcaJvWy3cbvnro'
        b'e28AIL/qvjGgXhg4+hqAXRElRX0sTW9e0+cb/Q2vi1A/+M6B3bNP0gSet+xED4jg5DGgiEEsAbtjVgYAOt09n1su1WaiAJ0ga0kN'
        b'i3i2Z9JTa1Bzh/q2ZK7PKvIZpQJJ10AFXsrF2UbgiCr3ZYchgPpzMKNpcV+h50Tv9BVuzMWqSKiyE4RhnK/CUOX5MYgPIzXbdYbD'
        b'aKX+RsZqk+OfpAkWuqPFMTgLP2OEiF6iylMH9bxDoCkWPjKKLyAZ4E5Bmw0nJ/DfwTWK5x1fC09svIrfs4X+Axv1HjfXX4Az8256'
        b'82b69/OrH/03392c4j8nE//9u/n0duZfT3+e/Xjjn19fTN+f31z6P00vz+Hf2/nsu9k7fz6/vnp3e/PzG//m6u3c//H05vIgsujW'
        b'2nTt9E5Z1FSjh8DJ4ttzj66ZTfLPQaA6Vh2q5ICaiO8BoO4fqYYT+OrWqUz8NpJsI3tsNI+cDbptEjRZou7XpaeWp05z5F2NxC5N'
        b'SvzrFfgeDj2Xrjt9rju5O63ck0PIEdN2M2gKLTvIt3I+dcSldWvrb4KYIZVtbSkP1LOB1/p7Cj0vryj31jyLHg3VDfXbL0UqrN7Z'
        b'x6Bnfbgb1QufhbC3WZhrwPn9WLScDuMEogluzoQZ/LTTmpQwNHKFgZUr/PRcXiJFS+kiU3s2QZFqn5H5Nb1ID7c7NX6FUD0wE2IG'
        b'yCYppldjkwVJFyaBdXgYY+r3Ecuw5AiDhtQ12ENc++fu0Kqt0iutspe2c3V/QLDUt6aJT1TbLfYJqNq52jOgvz6CfzkB3xqyOOIz'
        b'l6XgKUrsCmxPNv4mjrUJmleqxvn6bEBJAOAaTBOYPVPHmO3oK5B1GV93OrUXt2z7hIQzTf8cJjLFcwoWHaCEIZIxDIn7wxDtexgq'
        b'fSX71W/2WIycfYDLk9bfG/w3Wmos1YlPAAA='),
    'tools/research_data_access.py': ('6b702ebc2a328ab4f830c486a9a911b6ea67b4e1a0641733deff0b9e6243ad9f', 35058,
        b'H4sIAAAAAAAC/7VdbXPjNpL+7l/B23yQlMiyPXmpOyfaO42tmfHGlrySnWRWq2LREm1zRxIVURrbmfN/v6e7ARAASVkzm0tVEpkE'
        b'Gg2g0e8NfvUfB5tsdXCTLA7ixcdg+bS+Txff7v3lL3/pPi5nySRZB7er9I94EaziLI5Wk3v8iKZZK+ilwSSdzeLJOl1lzWAWreMM'
        b'jaPZ7CaafAjSVRBN50mWJemitbd3dR8Hd/EiXkVrPAjOToMkC9Z4OHzXefX9D0F6y3/Fj9FkHcyjRXJL0G6eALQVUOcJAMerINss'
        b'gVac7UWLIJoRKk9AY3Gb3G1W8TQgBJOPcbBeRYtsma7WPwIsRpqn080sDhbxR8BA+2y92kzWWRBhNvN0He+ZDkGd8JjFd9HkKRhM'
        b'ZukivjLvTE/MbgIMJkBgHQfTZMXLALwaLVq7PazZPAjD280aaIVhkMy5f7RYpGtegWxP2kyjdTSZRVkWZ7qReSQt1CJTn1Z0M9Gt'
        b'LqLlMlnc6TaLdfy4niU3+nX3MVkPAefDnnpw90eyNEPG62QeW+PFTfO0GeT//QOT1/3lfxihtVknM/MUCwPkzJ+p/vWvLF3o3/No'
        b'fa9/p2pWSzyz0L20mqzMmLLW5q/NzXKVTmIsjH7yZH6u4/nyNpnFAn39tMzXU63U5Sp9fLrCC7Xy6zSdZS3s710ICsHuPYWz6INZ'
        b'lXP8bgaXg+6bs9+awUXnt7D/+m/dkyu78zyarFLTO0s3q4m1jckdSLgZxItJOo2n+PE4mW0yUGcRhD5b4eQ+nnxYpslCL3iQRbdx'
        b'SKtl91ptFiGRSXiLnvcLLElIJLCiw6P6nXauOuGwfz046Q6bWO5VFodToJPdRzhvIa/V3qD79mx4NXgftHkH6iE/D8NGC3DT2ce4'
        b'3miha7xYZ6OjcXAQ1HjUjGh4cmCwpodZvMY07rAWWIqPRy0igNqerF/4yxFGqGFonNF93W3/41Ftb3jyrnvRobfmMUHbz3kFN/sq'
        b'uIxX+3Tcg0mczLCdOLtYuSwL6Eg/BYQ3qJGZCHZ7AV6Qg2jt0f697fa6g87VWb8XnnZP+hfAbTjsnoav3191h8CA2NDXwdHhq+/U'
        b'//xeg/6v1O4oPDw8pH+BVQcDP2Ks5SqZJ2viPPg1iUHDk3Q1Bb+Jpxl44goMJSN+Fy2YH7WC1+lmMQ3iCPz0b8N+D6CmMdFJcBPf'
        b'pqsYvG2WToD84i5IwKcumS8H6c2/cNrAbZMFaGlKb+fRDB3mwCED8cyjTCZLQM/D87Ne18zvBzOvr4LzZLF5DAbnZxdnV2FnGNwQ'
        b'OryWi2AR8UQ0BuA7GMTCLLiJ1kAbXPUpiWcg7RYAXhGXTYihZjEohrgiiDheLVcx/nsgk1vpzWsG4IO8V/Jiuk+cPpiAQO7i1t5l'
        b'Z/D36+5V+Gt/8HN3APzMHL4/euXtkdd2iJ3tnVLTbw/3Qv0SVHg97JzT4/pegH9q+k2395bW6LrX+aVzdt55fd6tNfO3oBA+QeHb'
        b'687g1G0lcM56v3TOz071SHZnIW0HXP/X8PX16VtqJ91fn/dPfgYNelRGnUpeFclWw7FHOOlf92iABk7fGXA/6Z9fX/Ro7p+kccJC'
        b'bI5THSbT2jEO5nqFTaFBcaw/xCv3GUQTCXE65TG94f+rcaOPUTKLbsAziDvRW5Ib4A/zJXVNl/GCHi7TjE9HuNjMbwBf9b5P7u5L'
        b'Xwe1WfqwpSPEchZX9PyYzjA3erlIwQfuIrf/897eHkvX4ERxzO5qla7qv0SzTcw/G8c8CMT4m2SRgCyXmxtoQjjTt5ssmgVEsM3g'
        b'IcGJ3Kxx3tOPCZE2+NcSZwUCgJQDMDqsbxKBWZM+sLc3jW8D5u51cOppQueqyaDUcMktnwnzUp7SP6soyWIPW+6ooEI6rH7fMPtd'
        b'Rwk4X7hKH0JWner4lU/nhNBbfZTjLRxln47nglUyOXwBzjgfzK89xva14i/Q5QhcB2g8KE6w4LHo9AuMqeEBs6cWEN9AmikGNk1Y'
        b'k4lIVWoK62ZwH+Kng4+0A4rFBXVmRQ/3+I+IjUYT2tM0mEHAQPDcxhBK4LPZDCrOj8E05cXbZDFDi5inQug9zVJIjFm8uFvfBxFz'
        b'p81Ntk7Wm7XMVC+ZHnYObXD11NIrxv+XXSOVgpeT5knTYHQg9eRhu82/nRMHlGt0IBUjaDA0jLhZLYI6dJfWXbzOkj/i9FZgfBN8'
        b'+wr/cd/42kv903MDTQ110D/ZZu7B+9AoAPrY4Bl/aAYfSVBixBaIe57VGw1DSSS0czISEuJtaZKejKfARB5bVCV0I2LYrCdvgCxq'
        b'ubSC0rLG/4CGnBBZaQIFbSVecOv2zgvSDEaM55jhPNyTNqCg5AdpslmRKgOw6lVrmS7rjfy9zOSbtjei6mc35HMszX9q+2uzM/PO'
        b'IeL0M4HpoTSRHTv7rNGGqo9funELh4d2cZemvEhO43hWNjYds13GdmhaFkTTkhYbzKvr6q+cbK7B08Tiw1C02entLVSDOOi9H3aD'
        b'+3SWTKOng3vQCxTCJ2Y+ZMI1lQ0XGUvTUA8UzxxlVpZXR6SpiS0XJovlZh3ebSLoZUpHFpsVqvN8OQMfnAqu+Tbr52DU9KIZhKCd'
        b'8k51Z7G0MdVCK5jWZvpiVkHpf8wNLNhTk0aBtjR0YSxiRSdZSocnWteJs2jNo/vbybtO720Xqs9wCEKzqErvCxQ5gCQ0bRjSDlZJ'
        b'vFy74sWTPXa7Lv/vRflUU8iEJ53zbu+0M3B0p4ZsT4/MS0UtMGTiP2JhNrlEZLqUZ8UToWZX5Ac4D8cGIvE4xfniJ7Ai/Ensj4Fq'
        b'BvjcqBjQPQZqwPUGW1MvwndAOweDn+iZisarhXZ9FT00iwwkf0AMEpISQjg/O7+mK2hp++li9qQU6B8hudYRWU6ihEPtZkIyx2Wy'
        b'3kB1IYYGTg19BcKz/OCoo7F8iljCQ2guo4qXLTUHbvS7TSVn3K6Mlnw62aKH21RSQHMZtcjinCw3OIlQMOpHDf9dkobrezIZiy3S'
        b'pdg1bSapOlYrvNncQqlov4HGRt6P+1Vyuw5FCQ5p2cIZKUJty/RoOkfe+kd1JouchOHK7Y9/ckRg1z6JKnX0/f6rQ1j76yS7fWLO'
        b'uIpZu4U+gk0m9otNY2eX2Pk3rHzGxGoscOztAqU/wPwUx5lvoIoapyiMTLsFQNAgKXnUZgHIJWNnky2carzhITN/fhvGC1L7pzWi'
        b'eOUFamXJHYxHeLzqy99bl0IcbyCK2YkQzckSzFypojZiVA1/jE3iTbG2V6gOYtwZpZ6krdd0fM76dKrAI7/+WsHPF5yOCfWUbi19'
        b'ajz2y62wkKRUEv2xrse8gd60YEzwuWQeQb4avPaI4TD4KXDakp5Q4k8otw4bJfg4kHz+UGlI+pAKkwjvVulm+TlTUT0IDQevZtEa'
        b'zkcHm5qRGi8MDjtwmItq4p2skkaLu3LkXKJZaBjc1DSrJ43WGu7VGY/Bh87pZi2AQLDnrIH+FZhtnUjJZKAwSu+S4bymf4qyWAr5'
        b'ry/gHT/SESWFgvkjM4H6qM5CkR4wp6s3tB36IVlMW+A5Gdm59ZoynxtQF8HD0f4WltX6h+98tbP4j5G8BJF22TGRtAQe+7PTB1QQ'
        b'DUXexL9DiGV1PZWmtA31IRbm3Si6YCyNCMTC0qCpbdWcIJseTSo318IwC+C6CvkpVGj+PxNZ+4fvmmR6KmmTKTSOS6iBjhJ33HKY'
        b'g30byx0OtkfbCn6Rwu0Xu9G5u0QgcxtEyfhu+z+F1kUPh0eHpfVIEJAHOO8+74Cl75ngjfGeT420ulYfdz+8bVM0Q76zBQTYscZl'
        b'lIxHDGfcirJw+VRXqEDfiubsiI4BkdzPsYfQcwH+A6JHGEDFCdgVUGgDT/OEKYKHUdqc8sGw4sI6o7K9la9FeHKRn7OaQCEtdNMR'
        b'tiH7WLR/GWE08swiPhOLFydIoRWo3W0VwBXI5CWPFGx62imaeKME2v8jKTEnhCJUMbY5eDSLI48l5S/bRclXdMAWzDBYfR7T9pgQ'
        b'OJcZ40tss/oFe6+4GTN1JhDrYeMFZXzHFfX08s+0DAssp2gMavJ5YDun/oJ1lNtFfTKIYgo7gJZvtBYtcbl91r/xnENmdnACgQ14'
        b'm8utIeiRgbiDsjXcHy05bC3i8/U8Jgh6PvIFGLF6InLSRLXuJ623sl24lOGmyMfE32pQr0nrYYXp1G9q/zyskUHyg+/HIu8yE+sX'
        b'mpz2MD5+sK9iTLFRjpOEbaHzYxlq//H3v9eaLkqNQr9bBEbv645DwiLbfDtoUeAwWtdhKn0TFMI7LagY8ePOdFztACGLFs8/d2BM'
        b'HMrJxHKowt1C/qJpzhGxtjttQE7VSLRQIblLbW+b0JwOeUp2hLjIF2mwWXBAD9R+dnmiPPbXC8qdgFmOp/ECYmQSUwgoWAJBcgll'
        b'EuAwo2jXAfnZAk7pWKeAL56Sxb4KxSv/wwp+/svrgwe0PVAkzOcNIQESHbnf9yDm9aWAdlbmZnfTDFq3WNiQjMt6TTkdag3bMGtu'
        b'jeQ1LMC0g3qqxMBrMwqB7hjsaxQCAZEEAkQ80ap/wXm/SdM1SCZaUvi7VrMyJ5qc2mA4kUmMEFamXEvyB7k6VrzWdfPIxHWbQR2M'
        b'jueO8/dx9N24Qd5490mjsSvAN8Ozf3R9mK/GJM+PfvAA68e7QwcB+bC/L+D7/efge9IfELqk2aNTuZzKTzZYOBMJSHN0TG4H2okW'
        b'RZCyfPwjWCp2IoadAhFGEz4Sars8MbbnizV/ubyZfouZ7oEs9pQrmhw1pAILwvFksyYHyRiLXB+NyWwLwedvNnfINmIjbVTb79d4'
        b'E/DrNRH6/gT/NUSXu694ntPNfCnzpAUAMsTM/KCP/5QZVQ6IXlbE7lXX8mi9UtKRgJas0sVcYjTsmUsxV3naDPqX3d7rcwDsXV+E'
        b'V+8G3c7psF07wpzA2QsPq8zSi5/PiwA6A9LbvMeNojpAxrBJNWpdxbTR0eqJvU8NEhrC+1wbAjSymbFINwlMlMBTV3tK244+bRYK'
        b'IvHbAob/BL9sWx1Pu7/0rs/Pmy9Y3UrTXXxsW4sqMQeCX5E08U3wvasTg6og8Fj7pjm0RJPlPJWfAhaFxPIK4rDMiCpRBQv9RsVh'
        b'9jHMuMzWLTZti0mrhX+BrTNPKLWbQWW3lNNU1+oI9nORwrcBDYxN/BIDRHheyTZ8kV1SoVbRP/fQNSFB27oN6562upfPgzZDmnNA'
        b'mnjyThZ+rioq1W2zsJU3BbLCn/FnhkE9yIzUl3k7laM4Iy+RMYzBPce2l0d7BDjuCE2q7PS6qysgGxq5Fww/14MgmlKdBitponHc'
        b'3XwuB6RPhwKH1dN7/MUGs0y6hTgbRX4L/oni6oD2dl0eZRvrrVIh5C8wfkvthT/fyq33h8q+tpjylbBVZEwnlKmy4/hVDKpgDyMB'
        b'xgmMKk05ozyuCIE8naKBw9tgXXQVt243s9mcPFv12ijavz3c/6/xpx++e8ZpFkgWZ5AM7FplxJIyi/UQRMHt2sUZgru9t+FF96pD'
        b'eaa1XRGTqCv5mpF3QWQiOT+uj0pr0ioMCwp+dXhodYcVA+2pwTYADu2n2nXv517/1x6pOAoz+tk76NSeVYpV1dQkMm6v7VccMzNJ'
        b'CSa/ViiUXG9EBjBAIjLIKPjG+ekwBTqXZxji9w1IgDPbFThkhd8lC3jrogfyqpn0OD2hZEqZD9BhdX4lUoQxMFJF1yrzSQ3dVACR'
        b'3AK3dIoRVg9EXQsK588gpMjT6wCcw8Jh/AZvTr799tv/CvYPD4+xlAgkptqB+xXwgLn4YZE+LAKyKme6N+E34YT1gDBGChzcJirf'
        b'D0mca5Ul9XnEmJ+M2j+nn7573sd/X6n/XvF/j63/1v/7+J8t/Dpq/vDc+O+a1Rlv/vG/o2/2x/gxOjwa/3P6v69Gh/vQmfHn/vf4'
        b'u2FIXRnFa0U+eVBDlqNmKbDmTCjT7+z87Op9mSJodDqdWF23ov6GVcDyRZzkQTGMQobhiy4yFwuPIRUWXnDKM/ntM14yH3UcpJc6'
        b'D8i0+Tc4TcmelvEbcIxu+ZoyQoR+i6aap6oU1zZfyx2XUgYtsFYlk8loF0D0cBklq4wTO+xwgNnyT897heCW8DEKhVOvstAPmmmO'
        b'pTeqdnp9eX52Asw4XTv8ufu+IB2p5Qh9yR4VzuUtl94/jTyXqEQwJMOXqKzX7705651hdCzRNW1J5Z5YljCbKRInCHmhwvs0/dDm'
        b'n7rOQOPQ1j/cc3G9SGjVC8eiGQxg1nL2gRyTghsO9ohFjHjVdCflGR65kvAifdAGlNAHp4/IbOumRKjJ7qtmkMchJbcjd/koPEhw'
        b'60aNKueyASuaPVvf5RrH7gykMzh5d/bL9nSaIv+gnVVhwzKPFk8SVCtTDMkX5DjGpOBFmkO056tTe9cZvgshmi86VyfvPPYTPZiE'
        b'7PCSCzdMuVWeh40yCnZzbhZQEBeUYUzlOQEnQNFzwp+KcDKqI4NAi3XtGtnYydr49tknG1JWdxgiJ2922wysXZXGoVTI0PaSkyXh'
        b'jFjULSz1G2vxCUQrLx2zNtNtYkCRicVEUQHa7SYIceBzXJLFSpAcnPPukgGrm1oO0zLWpJsp9uQMzTnXIAL7YYONf/yDrT3v/IzY'
        b'5rvOWc9nXUzcFefntvZJKoOeDxTMg08KCxIZhYRb7QJL1rkdRXRWMhmLoKVHkz1JjW242pPTZk45DmbtFWEhSRieaa6QqhVcJy8u'
        b'v+YRZixDpMwKhECZIRQ4skt5NuswMCgSnWkg8O0njw2Hk8ozOqrF7agdl1lpGUcPXFp4EaKh9QqgI/eEjLdzNt5DctEhtwMOwZo1'
        b'XxV84vl+/aL0YxiokSKRK7xeysa4CNCmVfLWZnCHQO35usAjEIWJZundrjwDfOiSXMYr2A7EwWpcMoHaW3K3HFDC34qqG7inGAcR'
        b'czXYAhHvJ3T72ZQdMoanqWq3doF91r+AtRWFFNdEthnbugzVzGsS62ZxChnM1E/VDoo/wEFAncX+BbnpPclQdtgZGjOT+wiRwpom'
        b'02ZgjVOWRY1Wo5raJcolVFzT2bacN8CWPe+/LUNIb0pbBoRmn9wmoBazknV/cNVjVKtabEGn6q3GadA96Z5dli4SYxKu2DsXFuAQ'
        b'RagcZfWkkJFAAF5SNZrBz7FOKaD06p30D8b8l+7g7A2pt+RheQM1pHvqaVj/Y0qd61Jk3r5akaIv6sAAExuwdiujke/vWLKv+W/y'
        b'0uoHZMjWxZHRVEXkyXwuIRKl0/yo4pmqtHuC0kv1qrVn7fCxqay2Horz7ViF+zDWSYTisoSsZS50ITsApzohOzyS0i4OFeQ4qBqy'
        b'j0mMehej8QxU+OgU6zDgfTzeQU/5mlyaqtKWTmFbl/F+nmZiYIio5gJgB25DTpw4Hj3VxDQUauV4jah/FtSKPpYML21cEORObyXP'
        b'SxKbnGYimiV9sMYKqVthDBfHvm5LJca7wUNO1F3C5Y4p0rpjuf1AQtIqc7ymN6OYfKgC0UWoCp9M8PxUw/UKG8ThqJI4a03hcXlC'
        b'OeMnBzs9M6qBpHb73IwmAhS0+yrUfA4GpGkZMuWH+o4FL1KW94Vzc7qZSDEoBzsPbjbJDL7oGGF0EEgOq7V8qj0/21Mnp+CwezWs'
        b'las0ul48mcrvMC/V5mcgcBBIwuVDchvBcrNaUgWOu0NOIStnULD7bUoF6nRQzN8xhdngDkvmKmOrfeSByrtKsU3WlvQCsmApkY/x'
        b'WrGRgUTPlN9axw3CmM4vq8uSc45MiCfdIdDiQhiI5kTgMygehbcRg8DdMclUpkYpPlzXYVs2nPGxr+7DIFcd1PQpKs0fkDKBdKbg'
        b'VylQzfWztRQHZDMqUFfKBbiZKv1mdx857bOmKkSVCiSSDWxz6TIkqzBAqyDiSGSTTCreI8VeLd2JYEZmOc3KTGOiNlWln8M6mcXR'
        b'YgMn6SxLJYUkMxWGUoVLDOpHynVZUr1CRlWsBmjCMXhalpYbujW3Yki0VucLZOXaLh1UFq/1lwjWoda2S7vFcIrQclvTtEfG7e1U'
        b'3faIvCSSlBN9e8sJsP/YAsWch8IT53C07YNSAs0cnPxnM1//tvllMYzw/4Fj/Bssw4e0fT1sZmFN1GIZVjZRPjuWJMCQj2P+2Jjl'
        b'Wm6McpmBiKaOgGi+a8kc684dUX2Lq+cUafASkn3LkRFnTUtLSdQyO3irZxKcmSYZn98nEkxaAvNVAyuJ6dJvSi+jqkoK2OQR6+vB'
        b'JRRSazIciXIW2TRGAsPw+qI7qG1RI/y9r1N5X1MUyEbDuDrcZg2qrChRDsB+bdiPllP8kfXBR1UZ5cAqwhHnytoflTWBEmysKZ/1'
        b'IGsx5x58cV033xjR40xqPUpAW+k6TPIx5xWR6989DI2m+xDtCroMtSPfIMH4qW0IqEWihatUB13EOIfINDnrnfZ/rShHsk6ZU7Fg'
        b'v6CKhSOO8PXOLpCo48X7jZhs5x5O5ZUoFaXb/GFOTKVwyEuoBjlVs2JTmr4pfy3M30N6REv92MgppwBuXIJpDqCdO2fW5nGjUZr+'
        b'L8Rr9u5Rb6AZe/sM8lo6pUKGRV+fa364rNP4hnAt0PNBzorgA8z/IDdg/lfTvvKlUUAgNyhslLZwAt3MsiUMsKLhoO4oKi6l22UH'
        b'28BKOaiwDoTvuoDllrFpGMHH2LCPGSC+ub66HnStXAafXXrTYjEU0v1RuPrFcphocUJVdU6P3DapXk7dpskF0270QL9jxHGdwy6c'
        b'NN8U+7mDD6OveK6hWzOWL6vthbdsk2IGy6fHkT3CuAj72XDmfDQ7klcUwQKdZukD3ybVy2a1TdDPpS6NWMljsS/xQX/0dtvSMMYl'
        b'i6FASi4ZTVIGDXv9KwifcpqjXG2mIe46OvTh0vsS07xow+rBCudESJhEWw6KH22jUGmRhwJUxk2ewOKHdGnx4NlXl/vwjUTAEPfn'
        b'0E/J8w2XuKRi8lTzgo586lQeMmEHYLZjkvw+sAUnRifLW9bcl+XC0m1j610ezXsjsTIGp/e5uhSO5gGl6WrQQSwPzJjYCKtfamlO'
        b'kGk7NP67ohfDQtvc88gXw8VqS5HW1KU4pORTiasd4DunnKPDHFAc+J5dlHmLYtiqfl/bpohm5t6GXDLnr8qZD/d/dFTYxy9SXvfK'
        b'y18ZmEGCkuJEs+WDBLbR7Q3JNWqZv0hmQ+mdusaQ0oaQnhNwjs4++d4ZKjnC6UKWkoObT1ixKlIKzEOXXxW1bFWAmyvxuufLmC/J'
        b'xQ8a2PibmL+o2D3z3rUkcni8H+JSxpCECiIHl4P+b++ZaukvnQfmxqRsY6R828p0QEF+ZCPOHDNHQe5/Us28kztWJ8A6bWWZwoQ0'
        b'raSBWcGGcJcgJZqjqD3i67M0RsyVbuPJ0wTHQy9v9WwMO3InQibFKawIpAaFfWTsn/7tenjFZkVxQSsYq9pk5TEMudoMxqaR0MVz'
        b'V5Gi+N0hKX5m8QsAx3x8Bv3T6xPkrZ/0T7uUvriFfev+dEOsjrvQnXZKD3IDMt7akblcycjp+BV4FbROdQ2oAVm9dALB1pmYW8lj'
        b'tp06vyryCSmDwsnNZQ5As5TmRcTv87bmkr6mvkyWTUNRNR1G7t7mR5yi2MiAEH3UV3M0CM48NqOVKq3qaBSjdlYvVx8e2bow04Kt'
        b'UWvBhfTastsSxLXxU9nEY87czWRGJAMRB/SU6nzlKezkqB/8ZNtOc4My5ZhfSIorYii7q8ZGqggAWlKE16CU/YJj2x+8L9U+RcwJ'
        b'yuyHJmvCsrYJKeiI8mrs1rD5I/p4EivEJXRWd68DgTt69Z/u5Z0abyuVyFPHiZIVyvpA+bPPFXKzGLl0I/AvLga5F7y1wET46Zi9'
        b'P8XlLktnV6xWlkH1LlmF8ktgXq5oIAt3jgwLXBU9DfmeEykX55/+/RUqau+4QpwL2TI3kVHqKnSYAi5pvr1y/YQw0ZKKEec36Uz9'
        b'juOFKqSgfz89y7+kYbjcSV+HJWHaMjcLGhiWQpcqiOLoXJdgKMS3Ali6KySBTg4rd3bVXkgP0t1zq8DyqGmJ6AFxxIt7j2p+eyp+'
        b'zSOU+K35VzKRV3LbG/3WoRr+zak/RSvCWBIaSyOCdsJTTVb1HWl8RC+5Horykr82WOgGp7YJdtFBlZhfuKEv5CNJYg1k5jYWjYtu'
        b'8yNYv+FH7bnCHeXt5yhfLcGnA3cvVKuDXvwQvkdIqbYrHFp8hQgjwIh0gEghV+uz1UTrxOuVYPt8eH152R9c4Sj7V+B5C3gTIWxF'
        b'pGtvMGypf22yNdMUN9h2zwteO9qyQBRDr/MrIT8EH7xSGp1oeld9iDYklUAA96A4l2mllgL4ujM88yuCkmRqYT3yTkGZl5J6qNxC'
        b'm6/QPbn23yO04/3OD2aumJ5CWS2QILMll/40oTcdauJjOdaVI2VLqmDpFEjD8AjJ/K+R/BQsOf4wfH/xun9O7Or8zLt90SZFM79m'
        b'KTRrymjkchy6kB2yTzG5kZaDY5+CcxZIcafoTtvh6pMItbKazBfctp6rVt0Oc/BJ40S6uv7tzptvFa3CiIRTCTq4KFPd+pqrVtQ0'
        b'VC9qVcVuFk9XTb2cz9dwXVNVUBEAsJRL/7OK9EwTQ9DBvO3ZnCbarAPfeWKNBtDANfpWVO5A1mOfA+a1UoBUzl09lJOt9xIuJhDZ'
        b'4mtSQvXhiPqL5cTFoudT9dGLp7qkfbbz/BpJSduvbbkcTGWcqYSz7ROoTjGj+uXhZedke6a7/49Sjux8T5/w88SFSsycjMa2Ijyt'
        b'z1ivyAh28w29xs67WqO5Zc3KUwVdeJXphhW7YaVrVuYSguusN9Mn+hM66IYMMFricLoizjKmM0GZe9uq0mXDhlfXp+9hp1C55Xn3'
        b'qlsrx2krTecJmJSmhvvfzO2YuFS8/mmJVKlMMvKaVNFG/Jy7qIUe1cx3DSAS1P1zzAjQFuxp+bz30n12S/Hcr+vVcM1Fy8/lM/w3'
        b'Mi53Px4vZWDuvOxgFpy25843D1aMclbPHJvyzbyb16ygs7gHGSYRljjXttAmqzsl3kHbM0gCGHaqKDnXPbkS+fQljVMjYWooVVzE'
        b'CF1Wk83cpBxNSTH6oA5fmD6rvUz3WpWulkS5QOZFxngq8bJcwP6JNPTn0E+5kCqFDbN5wAop2EF/0HnbrVUVlOtaItF8tGuBc2Pc'
        b'YiO9SNpeLCtl1zXmcPZEdDeSuflRJXrRzUxlOlKzhALKUpycyw/aL39xZr/MpN8Cl7O2yj5Js5/7AQr3lHrw6XoBd/57/v13pp1V'
        b'0f9yvb/skHg9Kvwj+mJ0r57JupZRXbYJmMcvq3pob0eKP/9LDCW3JqQPBXtGqfpS7UrvtTVhWyr5UzVQhVluuWF0yg2BdL6wMi6/'
        b'ljB3rGoHJnf1XLbjqqnpUek2DRuaytTR0wsd/23+RzUXLXQq+nmNZha+GfQvyrVwY0RXquB6BqZKzfZmVUtHt91I/Uk2V8UXCrYI'
        b'oipY/qJyjII90cMdZr/bDbmV61JxU2/1ikitMqPMlcVfbllY4lnfmb/gG7xgFtL9wDqxZn2P7w7c8sd06nlN/g5XGElr9sGqmUq2'
        b'gPfVH7nwSrWFJ9TOkpPF1BXOL5kjdsX+FxglpYNuUbgstkMfPGJKQtKbPOGPJ42bwnXki0dj8iBXoEXXi27tJw/4m0vEpvrvzk9Y'
        b'E+/Bx3PVrbq4hnQ5drGQu6PyjOQ3pFp17uQqdrzxxS9U5Kc0XrSi6VSDKLaQqzZUcWYlHvw5me0X1SgRZBLm+G/JrRk6jrvyi4lo'
        b'e6SLJNA81W03B1Lqag1N9o+VDYGeBJpYWbmEmtU/9UbTvng9m3qu4pDSYwWkdLmZTvr8SWV9Wq6nRn41ipU26qRPmrDgaCXiWH0k'
        b'iFOHVkWxqFIUZciq0+wmlDIN+tJO7nfKU0zHbhBB5T7LVpkBPe6mtQqzo5CrBamaz8pMtnxmIvCrdB61pX9tu8nh8AS+A/WE786G'
        b'XgDOozykRDHx8YKoLG883T+SakDKOjdbVUoYuSjMtvuifHI3GawGfvE86qVp0VJSuKE9i+Y3U3wu4jioF9eqWdzPRmPvM/1mVgkI'
        b'7aGpLd3qNyuGZZzzwd9hUSfouORCK9SCtJ2B4YZT7s0afmtYZSaXfMOzLldAFIrQLWUh/9CmagyOYBkH6qYIz3qBhQD6kYB/Wc2n'
        b'i4Q3A5O5yR/fbAbl2bB5fShfsSh5eG3v+5vkCdpXLSUjT6zttskbCd0EL88IzjML29trN9p2lq9BWDm2rHeu599OY23n2QFueuu4'
        b'ukKlUITj202V5TwvlONsKb8pdevTLEf3ks5B35ey6FZEeNZW1y/ILSLNgr1GS6sAKaNY3yRvOnEeh52g1K7KW3LB58lP7bJ8qGbg'
        b'Zf6ZVn5G4Lh8+1wvpu5cnpvjo+anBrW3JA01g/JMoLI+dqKQN6YRP7nlQMmBCGyEes/aZay5aYrzdHKQaS6J4XvVFUrtgujbuYyr'
        b'UEFQQSbFwoVGlZARRZvn5F/24eY9tSnXxSTRFdOixo1SinCt2ZycPCNXZ4iFdi5STtN2glI55eX5PqaXlQJEB08c4ZqEmFYsfu5+'
        b'LNk/lG5pdLusXrppvhsKOudL5uTa//ahC0tqdaUSOIw2qOjEJRdP+itVTsWBqSItfavrEcoorvgRabVb7QXFhpDNQvLLzmaxPy6t'
        b'UsvpdgoVrhd0a64moMNs5TqA/iaZdn9WRiK8lVbRCXY6axj8ySj5CJx+JDdo5ckbBZHtx2w4S8OJy3BZdUVkpcT/W6NP1ZD2nadq'
        b'bguh0HhaPLETjfKNVZHG805zxinj60M4T1Uku5l9/qqgBdA7/1KKoMAg5PqIwv0R+Q0NdfkoXuFbfOyRs7x7FXLM8zswLM0jwfD8'
        b'eyyaQRE1hvc/8mVyfJzjPp1ahaTm0n3x34ZErOoehV0u4betLPcS4L86Vw5/3gecvM/+VIKq/o6XNZsthQBWK4mVqKCFG8IIaurW'
        b'WU6ntvNY3vQH0ELdrOqdYHoZM143L4ZyvHs06isQHn+pIJWPH9zi6rk1l9YH0Q0V1Mt3P9TqWkZDBTS+2OxHur1Ibuah7nTNDuUr'
        b'XiSvqcJ8X30fWH2kXX3GvFUKkCvNaWatt/gP3w1OggIQ2t4X6rgIHZsWR/Nt4b0HuZgZreSeJ3JBlORS+pe1u18l8Txdpdflvujf'
        b'+rKrc7fGrLr9N9uut9vZ5fb2H2eXlSN7EaWKXFSaymkhG7W8/59z17V77XEekaLMSj3a3otnQmiDEoRc8ip+aYpvhePbro8dkqJH'
        b'/D0bus3mHJUdPRVCYxo63pY34FyK/YUXdRdB8t3WOlvWR2pruPVLL7ne8Z7u8u9dlX03m+NTvrzY9774VAr/hfu2K6/NLovo7XLc'
        b'/+SjXsLntWgpvWfj3/lIzt4LgeYSKfZ/g3r2A/KIAAA='),
    'docs/SHARED_RESEARCH_READER_V1.md': ('b7ac6942435fa86488058b3a1de2107517362259bd9cc59586d99233b12e2788', 11551,
        b'H4sIAAAAAAAC/3Va2XLbSJZ9z6/IsB9c5Sa4yJK8qDURsq1qa8aLRpJr2k8kCCRFlECAlQlIpp/6I+YL50vm3CUB0KWuiLJNEsjl'
        b'LueeezKf2ut16l1ur1xwqc/W9n3apPb3mfUuzZ23//ev/7VPj15PjblJw90bu7iaTafT5GyWfJgl1x/Ors7fJ1fn1+dnV+8+JO/P'
        b'bs6S3w+Sg+nBMR57tRibt2lweOvFy+nh8fLli0OXZcv09ezlcT59Pcumqyw7eHl4tDqaHk3TV+4F3vjyUDn/xjZrZ9vgfJK7UNxW'
        b'aYNFXtetz9yEl1hstqXbuKpJm6KubJlWbmQfimZtUxvcNvV4wxRV7rYOf1SNPTvGnu4L9+D82F5URVOkpQ1ZvcX6PsxG+FEtsNw1'
        b'Lti6Kncn9r1PV429vBrZqjYb52/d2N5gZbTDZDZNpq9tut36+h6r23qX8CM2q713Ga0r2HS1wj95O1ds0pEtmmAwRRNG+LoIFqvC'
        b'CjOHORpn0yrHFrK6yorgbBD3lC6EujqxNcbxP+3d0N4Dv0ez6Bu+rWBH7GqTFpUt8GzWyNqztcvuXJ7ga+9ui9D4nVmnwT5//sP5'
        b'2qb5pmjI2rcOA/AM4flzHn4R2AHzTVoVK2xgntW0ksadrtIyODjPPH1q39VV4zEbv+IdnGjMoqnrMkyijec5XDhPswzbGm93C1vQ'
        b'+jF1DrfcOw4+e3Z5Mbbn37HAorqFQcoShqx9GJllmt2RAR0+WB162RZlLuNm+KOsb2ngEZtkhXnXsFEgs/Zr+5jeOXs/M4/YCK8X'
        b'GeIjGshu0m2wizyMWyzYF1j4OE+LEktvap7D6UIN/4rB7uGf2u8miI68zTjoGt6nzQuE3b2TUSmysBzMtC3TjL1q4waQdBi594O9'
        b'eE8j0HRIvYOjY1uv+NPz5+477So6RmL4+XPEWpWVbU4GxHMmwPebFN9SRhTNbmS3zhd1DjOuitJZhMHa4UPti9uiwv6zss7uJLbE'
        b'97YsKpciDWhp3tFyqtouypT8saAkqsuW1jomSIEBaGq4ti6HAWUrh/0jT8mlGN5UlJaDB8QLFCoUDtu0WQe7dGX9wNtNSwqQHXlz'
        b'Vdy2HO4aWQburcK29rCpd2+MSRC1nBFJfCS5n00GsT35e/8hwaMw638sGPe+3vyWvOpsevJvhqqXf9AmJn8nC+4PIE5hy7JDxKEh'
        b'bihsXVasdnD+qm2wi4hPgJJ2WSL+2FQxZE8ELC6vYLyCYMDwU+QwjDC0be1tBgM1/MN7TxZcwf4UgjcdDFnKvi0ZvzKP2HNgRvge'
        b'0VzfKSjaBT284HDOaxc4fosqNClCikB3cYWoqdxNHAFJ+LCusevS3aYZz4KUaimXYdydrtVuihAoWPLCc54XZK/PtSV0LXJBPYw2'
        b'ikiArRJoc27jyzQj7BMEx8AApJJgwtZZ1nq1fJekdkG5v7D4UJb2Pi2LnM0FPAP4ASGBB2EU8xD/2qYxDRD/AE/jvruM43zyZ4vX'
        b'mx0lMJYXxnaxLQC9+bzEFL/8yjnRABNgagA/Q1vCduxMbMjrPY5s4fqiwQNVuoEnZE3PaPaMMyoosGau2AKuYCIGMs3P2hu1s+Rk'
        b'ooV86dbpfUGhsU6rW9iW30rIRntYb4EMZHu7RPE0DmaVANblScriDULa4GhdiLcNTPADX0ouKKQBz/2ywC4BdGS/seF10noCIocf'
        b'8u7PFv6mmKKtuXlTL94gahtHzqY3gcrOMxSxhwuy4IbqrcFaQ8slRA2yakNajiOjoTBrN1vek04j0AnkKVYFnuh8+CyYRWjafDeH'
        b'VVHSWmxwvvL1Zp5T9pwiWt3ihHYEONWSZ/kFuxSABJxViHL8wdvIjZCIlBByUFaKzaZt0mWpFU59SD5HfgT1P2GGOL2LwFEfbyON'
        b'QI23DrI1DEe6LrKIWAC+jwRjbC/Prm4uzj6aGLQw530RimW56xBUgpPfTyvyEaECgbXEF9EDJCogmov9p6Iq4H0rVU/qizH/ef3l'
        b'88dRn27s+MXtj2I7/wM8pgQkMF3ZbbGRy9T/2TrGazh0S7ty+Th+bTrfbXep96gATJAqNdQZfyXzvrGUaJgulrcJZfUkvUehTpcF'
        b'bdgAPNpNJRGzKuu0OT60Xz58fPe71V/G9qyybaUvwVOuQil0El7qI3Le2FylDxHSditUS2JwcS+FwGJA5lScyn2OLHcC5ALDiCpO'
        b'VG968FfCwBlI29m0qOgKg/Ju7rKSg5xeUWwT1BlmMhcrqgHEFD4VbzkgnL9PmWNhjDp3OThZA7RDUZPkNcs2v3UC+7MRuD79n5CR'
        b'EaslV/PM14FDnhPbw9I0G1uUtolYZ//TN4Z8rh8BPESOEez4gQ1BKbItW0ppWYO93DVrjKU1dUBfDMxHo+OZipgf4r9+CCeWAYo4'
        b'CZk8AxfHL2lj4dX/woaXDu84nl/2i5HGJjpJFgQDZQ3SQUNp2YKwE6/s1kQTSbgSYFMqSDG3n9mQJg5sOT5SYZv2Y1G138lrDFDa'
        b'mBzNDtgRILp4KCQBuOg6w5IpzLvLr6iXqF5JU2ykG6jbBpCEXQISsOVl2mDPAcEEIlRXLgZbajdARr9LQrpyyG2ESLEZm98QyATN'
        b'HlHdpZd9qP0dtkm7bH1Fq0YiNy6iKM8LYsfuJR4MG8BwO7HR7Agtnq2pVFI6CHlz3xtXETDYO7fD8JhjXTDSkR2VgRKbQlJilcST'
        b'N8L2JXt5yg0epsrSbVbH5hwMxJwlJ+NcYVAvkQdXghV5TGZ0ngWTDaLV8yJfULtQoOJ5+hfcRWNQ0+Doc5fzjP2LkVmgOazol3Vx'
        b'u6a/QUDpL/CbwG/c0zToe+wZaEQHLczkZCFjBhfOYLN0amTQiTrw1qlSVskSDYxLqw6zAZpY7omV0ZkjLbkNaCnOqUkbm3OK+z75'
        b'FBDAKaW89AR/k8LRqCSfLt6hGUJI/aipU0Zzg7449SMDeuRRHATy0/wPLJWbkGWKhYDFU/QzAm047po10qsffknEgyOKsh0UA117'
        b'VSC9bG/4iRqaAiNE+ECE9+vHPO8jpHFyjQxF3GgYGoL35Cu7rNsqj9W16/ABs9rajs3Xaxt2m2XNXgFJZiJNPwbKUos0cD4Df5El'
        b'SaBuqQL6e4rUrv/BKgzH5V5jRb0Npc0eOHBdkHouEUC8Ez7Gsrqyf2JQU+uKW0uiPG3ZjPWlOY+84ApYEv9i0MKCCqobAuiEIgAD'
        b'oXAEint0RkCTEp14pvACrQ1opW2TEoOP6RL526ATQli2nojIiMJJbEYBMxq40ly8J680cNzEcR2GbYgCtBvLNQKeAf5/Ydolm5RE'
        b'mGsMYIfqB/QdynUQCtB5dON5F5rYbpXXD8MetiODt2jHx/Z/1B5gSmZof6XiMjtXizj9nBtv9K/zaDaVLk4ksjDxtsYsQaDVkCcF'
        b'W1ctAtZ9F/acxIhOsS7s911cMktBTAVGFoWa2hjyNVIC88GypkQYZbusdD+lW/IzvYrKzRlJcWgTAAtMYagtsp8oFWMAiP1AxBHn'
        b'HfNIW/yEHNUmEjpB2htW5jrREq5WM1E1Q8DeOUdyR3xhrrrPTzZDcBHudclCwYLQ2GxDx+uZp2nERfCRYshNF9a1QhACF12ZhxPe'
        b'TlvdVfUDFL2aLKcPLJLp9M10uhD+T0wsJytIUk5keRNO1gHZG7aKCiHbAhsmpypSRIYQaInV7UnsxNFFxXWoBLLCuONOJp30Gg4y'
        b'WmtcT8sWlxc388urL//8BiOhEeb6N4mylbZA0UY9mYuZjLeJf6SlRoXBAwiKVfQm7UVzdYKFoxQ6EnIiMadWA7ssQ/2YH8qd6WnA'
        b'52/X55N/4s++INgztAyYafLZPcy/gSb0jqN56WG8cXZNFQXsAnDTcHevNaGgZkQCiwUy1BEv9WNJvRUG6Zh1ymAFgdUxZBnlYTG3'
        b'uMqORFIifbVZ+7q9Xe+pbRQfzP5oI3ZdUyO/01JUrhL6QCUkb0s0P1+jR3WrgaaPP7ODWyqhEl/E9oS20GjRdSTC9LLXg3N3NAXp'
        b'DcV3UGigUS89UE0r092+nGMkVEQLGJaZyWDb9O4jkaZRFnYVFoHUNl1CU1OK4SXsI3eLvyY9pggltCJCKQ67ChlAyKMdhIm17lnY'
        b'054QUtq0D7DFqfMlhkVQY6eKKG7g8go8MQNmnfMeYsceoZqE54UrYQfmXbWfd68oyrD99x8REaL2PQ5d74mTWjGou1DxKKbJRDRn'
        b'EDB8AYDw6OEUebWRNvpxsEDIS11PRj3TRHQyfWMgjs4huoNljvWgwgzHcJEYooGgXjyISgJ+u4f5/AKJSPFQZf7228359RwN1LeF'
        b'UfEXCTFolQfvA32bQaBvqLEk+t41xECWaAojoMvLH3YGVLTIhjENun6X2n0QCYj5i8WW+zRDPNmy/j5+TNpXya6LZTq4kbYXgw0k'
        b'RlLFVYIcxlY+GQiSqPOh6383NWe0UW3r9JEZfumG/9UI08Jj8vyY/vrFWPz35K+K/pORUM15z4zmouqO+JXIjeYEi6cxhefpA9w7'
        b'3/tRnlegPn0SLfRkSKgQLuE0Av98/3t5v2dQxLpOV4XHwYuCxaj/Fal+iirR/8QvKzebE0097Z6tlyoD1FUYDBEp2inc+sNV3WcZ'
        b'KqpJWNnpkxUkW7hlzqcuzj9hmFYB77RAfJL75n1MqKa7G5lf4XllvqQrCsYwIgoblIONiXQB8Ulm2XvyIwl1nkz0VMW/IZfmR4fE'
        b'NpKrigl7QoyiL1djCmjhyfHAgVkGK6c6esIpzAKHSA7RGgOuK4RF7WDaXtDTUtV1AcmDp1Z77cot6fCkm3QHVHyIQJPpz5CZZMDc'
        b'irn4HI610LlE7UL4TE0HTgUfI+JMk1niWaepd7JvbuIWtVsY6pfFSiRO0it1NxhqJzsIAgC/i1YeWQgd73EtlwPKQCd9dLL56Enf'
        b'PGxwisDnfZAzPZ1vwkQPdXde2yuWcp6Al8wvGmpUzrK27KeOTF44+K9dBAbawWDMwXnCyMiLKJb0XB8hE7L4JNaYGCMchB12SpMv'
        b'Nh+ZIdvZrxhBtdPIMVCxG663bBhROWMF7woswPg77TJE8qZ9x4AEDmC+03N/OtWQ00rHDFTcgCbmdi6NyI4PJAY+gPqZB8HT0CIg'
        b'hX7r8fF97+fuJFl1WKIWHEwgKW2FZhxsPmSet15UKnUaVfI4XKVa2OTLgo8NO5WUO/DBgYcyktjRZ7tOjmJpPQrAVC6AYJBIDLcS'
        b'1O5BT8EW7buL/m1qotF2IIlIOAx8xkpdyp7o7ElKSCAbb2HMD33HVugFgY3o24mr7gtfV6yMdOf1DyAvus8X49nBeDYdmcNpPGD7'
        b'G+Q+Ub5P7etZlEWgcK35wFXsNEm+jLq+vhJlVtcmturvEhBfXryYrV66qZvNlsdHr1/NDqezLDvOs+Xr2euDg6MXL6bH2fHq5fLV'
        b'gjgQ9huYOBNvqM3Ri8eWNpse9oval1Pk0IHUQjJzVP8OXoyn45msLrRwBBYLq7D2WyYiY+9fgcjBKhhhdHqd7o15/vz4UXPNZj/b'
        b'i24gNGbxOksPXh0drpbYdvYqPzg8OMpfHK9eraYHqZtOV0eHr14tX798udADZL5QwOgM5jIh0XNFh8iySIOfgbjE2fcXNmKcx+IO'
        b'H1/c0V8Wh7MtxsvowWFQHBqp79q8cWHYt+WJ1LaOgvFhLVRW/HbAGXQwxT+nUQY13NqpcwY3SySNZedcTJM1VbB/FM2HdtnDUy5o'
        b'0eLo2BDdwlaR4oRjETJxVaY7bxI40329u6DGZOv4No68VKP8behgw9yn4JqV4h8Cg7K7O+iL0Sj3eth6iVgvakaipgtKGu4eHsHJ'
        b'RzodhYiR3il4FDElWPPWc/lVPLQxHJ4NZDEo8j72RpSS0mqHtR7Za2OhalOHtkP7y4E5nfRiW2CBE9Uwh7g0tr8PQkIP9+L5Or2L'
        b'Xte5rrnFTF67wwHQshI7uGJAIa0Yrvek6PByMtBAsNpt6GsLgfeuu1UgOQEU/EKdvsTFXuDSmaRcBtDkxlpbwRenReJZ6O7wmEWS'
        b'qLUWHCQkTODKALNYfYk1NTYa4og5KR0sd+g/kfbBdJ25lNKIyUpRBsgsp4qEyiwU+nbLJ4k3tMOoixmaNBFPXZ5dX0u6sKLc35rq'
        b'toqDYS1eeoEJDd7Wz/vqiEpqEzky/Te1ltrTi/17aEIeWOrBzQoWwjqNRQSv8JcTw3h9wnCACm0kBhT4ERaLadO3dKiD04Q7Vi64'
        b'v61aFnT4aQr3sX1LJRsdotG2Nh7+dFmmORX0Rl2vryWsTvDkcmrah2YwXfGXxUVgUDQcC3fsUy3uVGUNbLEgBE4rPqQzH4VRvtED'
        b'0tBdi4rn0ij7unxSt1IP8Xh4heiku3jBV5/0pFY6QMRp331yvfpZWucsVDfjygWR6dilGbmJoKugCggiSEi84jM2moEpsYKQnhhc'
        b'yumC61VSwy0js35VIUnJFb/palmTFodDTepx2wozJX97wkHqw6NwIdKLOiHq2T1b5pa9u8TwF0E7Pids/4o1aL6VM0AvulTFsnSP'
        b'tINoHfZdw/sOTM4nZB2+lyPyt+Iz3a367eLz2cf51fl/f73ApdJOMu+athLwXna8etIJ6QA4T3dFGpekypOoIaAh5YqTy39m6CM7'
        b'lIn1Wg+JIrTTyO5ogMtZ8nbQnaTMRYGV8WSeDrF07FswyS3fGcJP5DegH53a0oGcqNHGdlrmfHj0iGM5OofuT9X0ytWQiXlHnXYT'
        b'awqG0mnjOydEy68b8vDZ5G1X2uJtH0uqJe2oY52xpOtFVNKhBpwhagJEqH9aDQCMBurSWBXzKNtNfgO+UmmJcYjbAC12cDXlga5m'
        b'8WCDO086qzP/mDISj1Q263R9++7Lp8uP5zfnI/vyWzfBoDWhg1Tf4G5bUU+2KYj+ZOmBuN7EXXP1ZpDgLm94ra5PEy2HrI3KQTlO'
        b'cBCz+dj8PyScdj8fLQAA'),
    'tools/macro_research_checkpoint.py': ('62438ff85c17ecbd0311338a7f0b8e8edd5907cb0f7031af89e1e18a546fb863', 18288,
        b'H4sIAAAAAAACCu1c63PbRpL/zr9iDvkQ0CYhyXGyWWVZV4xE27xIopaic7erVaFAcEghAgEsHpIZrf7368cMMHhQklNXdffhXJWY'
        b'GMz0dPf0/PoxA3/zbwdFlh4sg+hARvci2eW3cfRdz7KsyzS493IpvCSR0WoYR+FOpDKTXurfCv9W+ndJHER59pO4l2mw3olV/BCF'
        b'sbeSK7Hc5TITS7mOUyn8eLsNcqfXW9wGmYi8rcwSz5cCHoJoJZG6jHIRr8W8iN79+Cfh+b5MciADP+ICphBetBKXc/HN+6OjbzPh'
        b'e7kXxhunN4ukeEiDXKZILJX/LIJUrhxxEkfrMPDzINqIW+mtMrH2glD4YZwB1SDKcmjECf3bOM6wlycegiiSqYOS99ZpvBWuuy7y'
        b'IpWuK4JtEqc5cBHFuZcHcZT1erot3SRemkn9/FsWR/p3nDGlxMtvw2CpyVzCo+6SlgNTkDHe6qesWCZp7MssK1t25c9cbpN1EJZD'
        b'82Are735bLYQI6JuA+/w3nX7DqxYHN5Lu+8Am6Dm7Propge0HGTKAVXINLcPByLLUxsp9PvMcx7HYeZsPT+NXVi2PE53bhYXKbCk'
        b'5VgFG5nlAyEjP4ZFhx9f/LDIgns50GsxEEXuu1H80OtdfRoDd6l0wBwSYM5OrWtvuD4c/vnm8Yf3T1a/dz7+L3f2839MTlCMd4fi'
        b'jTg6fPde/UVvF7PF+Axefn/0ruPth+nZ5AreHh3Cn97F+HxydTk+mUCLpe32gAXKpX8bBb4XuvI+AOPz5cH90YHV6/VWci1yWIoM'
        b'JXTRasAC7CxfyTQdkCXDMqF4YBkkdv+4J+APWM2H4AsY1yrwNlGc5YGPZio3cRrIbCAiCZtEwJLifKlYxitqzuM7GWUiTslGMgeN'
        b'D8nB+x3wzfM6K4kz2VaRr4c/WqDnNI3TbARSJSFsJKvvhPGDTO0+ja2mBQqP1IR/vhGXevZUemClIvfuoE+SSl+SDkSMPD6kuOFT'
        b'MLIvaIaw173MIGLBjgxX0be5WMPmFWkc58fCcRxRgCXNYeqzADb75IsvgejKcsqh1ny8mLhn0/PpwjoWtpVC3xD7gkD0IMonsD0B'
        b'et6RFYGJZdhIQov37/5s9QcV0dPZf16czcan7l8/g20QYQ1D/yxgs0rNCFDQLwS9qZG5Wszm448TgwpavLeRLSKqvYPG+PPi0+Ri'
        b'MT0ZL6azC3d68ev4bHrqfpyPL1jiILr3wmDlbsC+QM5XjD05m04ag/0wkC+M/nyBDbP59O+TGoki8gpA9zT4Xb6Kjubi6mR2Oakx'
        b'kflxIp8ba/YWfor2lQdeSAtpsoHPuhu2YjefENZY8sOjmp4vJ/Pz6dWVngVsdRtkmRoCDmcZrGA6fEA/kmUCngKeyicE13aAEFmj'
        b'XK0+r+6g09Lmk6vFfHqymJxSV29JkIfkt174ACCLP++DtMhqxC9mC1fTGP98xgoFbkq36S1DGkqOFnnLwCfltwJcs5fuAHuinFZM'
        b'0CiPupD+wD0C7MA2RpCuzbmYnk9mn3n10UnEBe8v+Anujx9W4ArDABxpaeVNrj/MPl+cluyuwSOzMk0g4P0lM3yWX8Bf6AaBY7hF'
        b'0X0yUQpRLgKksW2MC4B4SgECICMsK8YHBpw54Oi3md0XwRpc8c7O8TUhJQ6jJxrV78Pcny9OzsZgJR+msE4MjIBuS5hOgThSKX9G'
        b'4tHa3oES2UqI+zBDX86SJjv9dx5bT0KGmcRHGs2IzR5BrEtX49bdiFwdPyIDT8egjNx9hMjJNrzI0/Gj1siT9kOZt5Yu+gUb/6cc'
        b'Df7UXp6aHW8JHr7IpYJ/5XltMhLQUuIEmZvttrDGd6A7VFWCAl/j6IF4Q3GAig1uUHNVaKeHWX1TRBygOExlCJsVoguDQT1/kGGc'
        b'5YFfsXkmiDD6FMghZzQrvE7zDI3ctg4sellaHv7xwhB05KyLMNx6uX+LIcN4+Hdv+DtEDa4zvHkLq5Iw0YTIgly25eBaOY7i2vxT'
        b'Cs/TJ2GQ08wNsbVYpPy9wq8gCm0tT10jNYU0JEFHIg/sePkbbNzswIyF/oUuOUgarf9w0B7h3QY2E+6Hjrd9eI0mR+9+v7lmVQ1v'
        b'3vBrVBfyNahpxhSdwkaG931yU2/wIBTjq7WVXxKQQq5GF3Ek65basOKaSjgGzWhWm9fxUPylNI4cotYMrBA8hfjLSFTxYX25WIXU'
        b'TTPtPcDMRAZiHc0qv4Ntr7k9LtWgGeKQ1obxfTEalR3r8916WcMqoD8oxw898DZnMcSVC733jegQAH0Hice2ii/JHrfSiyADAdOA'
        b'hGRNSLz2ihBtGcUCv6ajx1RuYwiTIIiM12WkyI0upWDg5UDsD+BnIR3Al7hcrhtEADiunclwPaCArV8Jjo0OttVWijq1+zgEkbYC'
        b'i9EiLeSAsd2N7+ixX81LeZ6aFGLMdfDFmLZlGxUfB8Ye4mEVJ7B2JXjQvLCoxzVbVgtyfdNrtGSgb7kCNCz9TAUEmECiYORZksog'
        b'DWnQjLQw1W436Nd3Rbc4ONCgSZmrQXSAdmRQLtOpZ8jxmIpmkWAooYgqbDFIrlWmgaKrt5X0dU3SnMyipUHKEm9ZY+yju5CgfG1K'
        b'qkMcxRduIMp+IHmWeYO97NZD7rhPnaVKITwStAG9B8pAcYVqnMI7ZELtyzlk/5FsbMz27kEr3r95qLvB8DfiIhYehJywp9Odej8Q'
        b'yxTyuvQAnP5GpmptQZwwREQBBmBTY873eX6GPg5yt5XTgqKGu9isUhD82E4xu3XzOPnu0EUHG+QFYoQXHvT/HYWu0t63LfdX2yiW'
        b'ncH6rQpg8l9JOrw+Akdyjd7kTd8qJR1UqbOrdGU6hyaCcJf6KxW+jkScOTKCuDiOHFg72zofn8xn7vzkbHYxcX+eXlAeSIvUpL6O'
        b'Q0hb3QDXBx2Mof5xJDhOE8Mhegws6kAawfEzwy3xtvV2Iob0UgR5Jqanjpgtcw8DxluTWhlFf4udBBVCcAAjHjSGgDlYLlIlJNQT'
        b'gTQ0rWDrYe4CcaoBczhuIELprUv1OGkZeAzEUSUq2htL2ka1+AGTeZTTwX2kAQZ9m49RUhWs6imt4RCkyahsZ/X7DZBshWg4w4DE'
        b'q605U3OV2Fa/E2tT2rcp7lpiFEA05SW+ABywyJOiBipMhozQyw1npdvzdFcXnKyfChmlZkx4lEkufvXCQk4oU/QybKxTUC4Dy1vw'
        b'rg8muFIR53GV2zTUzSFEYDBWmiJrW6cKle2/FdYB1zmzhpYqWQlaXiud4lt30XGzonb8P8HZc9NrEwllZKt+tI5HpnWofUnpd7Rx'
        b'49T1tstgU8SFOVUQrWOYQ1G5PrzpPWOH2HkA+9DPORzEZ7alaXYKkvWx0IuKbCULTHBfssC5gkHtFOGGI/+mPAFVK/KdIcM34pLB'
        b'AsIaMLUHmQ4AuXH/7YaqwrqqiuNMh7NSLHmrSq5jkJtLNQ6hA6O7nUD5MSmgcdIDOuzMhLcFvFhjPW98OdU1MYE44OzHSRT1GsW8'
        b'6URq7U+syteVcRhYT7Gux2s6iDKsyrYsNNIqODR2FiwTp8iY1b2tQhZFt5qTjJbnfAMuPau51gWYi+Q4EjL1MIR14YoIewmAYwgr'
        b'hPIpWzpCSKg474gLLreC3zfoeeLhNg7xPCJaBxvgHDZTDiuUxsXGJEpEBFX1U3TTXIaKizwp8krjeFoyEo93x+KeVuxuAD8wrKrc'
        b'nFGvwL17Zya8tqU8H9ohu8LT+fRXeO638lbcCHc6v320Pswnpy6YgvvL5G84+uMndzH7ZUIO9ON08enzz+r56cnk9lrPeDK7+DD9'
        b'aN3UfPJ13R/rPpUFwBK769DbIF5co3dB+xli85DtbhisNPCUhniDssOG83LAX15nq3wJvSldZFsxQvaWG4CtghnRyDgWcdIisq+N'
        b'CAMsaOslNgD9QJApQUPFNDlEWG7Mm1FP76xBCz2gB8RiwxBsJ2z0xXdYgKtqaO8OM2422n7Ati6yeZKVxW1FTTcNl0XK1bIj66Y9'
        b'GFZnBP9h9WQFs4wMBVxOLycDdUTQbldsjd7/eNhymfbsihzmwNTnggdMviR4htYMQNAbGq7W7ipzFZF37wUh1TH7HDw1ojWOwc0z'
        b'Ej4IofAsiCC6hy2OdeAD3qMQpnExFE9WsE4GDj7zvUQ6pp9k63CqatoLvLfPdxQFfcyDwQKaEPgqTLCa5PvdbrIiAmrstwoW1ayM'
        b'JGa9wiwlmFRemU1/RXhIL7gaw1TIGClaboWKjLyw29NrjuRu6oHeTacaaJSK+SJgJFctOFMZI+tkgl61laCSdR5YT8Ldpsugw7h0'
        b'595F4A0ocR9RUFlzJVewp8F/x7kXEpVMZJCHgUcAcxxug6jI1YkOHgNDtvoToC0eTgf3warwQoPS0vPv4vVaVcsz8d136Ehi8H0D'
        b'wmmFGwBBUpVt8Ix7jWmkYbWoR8BEuU0I08E0NtL+U2PTtWCw6YlJFew3m3nyKyJjlUAJUhzl20NvtQL7wzNy1CN45whS2UCuYQ+u'
        b'ggzPBb2UN7bHFcE2vTCO74pEeGs8lPfwABHRBatbXJo4QPU7EP+AdBRQXUHCStP91EEtgagUcg/07d4yo0NKgA3Io5dh7N+psJi0'
        b'vIRFQHPdyEjCEKdLcSmfqbYzAeNoso8e3+5MnZt2RrO/kFi0a9AqGGB2DDOADfPDcfe8rVSErAPw2slCKRP7nXjzpqTzVt0kcPiv'
        b'r6tiNXGDj0IM0FA1p+aOa9T+XqpsURSnbzE4C4n3CcCFn+r0W4HTyKLj+iFB5xoiDDwjyES+TeqKCrHkqg9F4G1fHAgr8XZob9ae'
        b'ChKNUdWzPbmUOu4ZCNW3pQZAzmC7LXJ9cgcxAlbEsmJrtV1EVaSi0bjeMDmlHwSFpDMXOyDEWK+v6TU4tso+Jse6MGY9zzaHJkrd'
        b'FOC8t/5AHe8r1xd7YYlh7/qqqktjhXUBM/+SW139uXrp4kUG2/pHZDm/xQF4JPYtzHsf0xN896wRWPs0yYIbLhSxcQjLag00E4M9'
        b'VbivXARq23pfynZs+f7o3bn1zAR+kYOrGm4hZsHun8ZzPArVR3ewyTEoqMKhGijwEUr5zrDc2gkOHtdQ8IMnJs2QR1l2x/lM93GL'
        b'caiJlbuKQiMjV2BlxDtcBCfB8L5XJVN1PecE1UseR2eBWBMR/q0XRAMVfKKRgWu+I2QvgxUw/ZxPYspTFx0aVfrhAM2qV1o64iKl'
        b'I76rhNO8FDMxRZcuwimyoAx9vYczPH1sjrEEjTx+qZzcPjoEC6GyfTUlmnREFbyS2j2GFFTJ7LAeLTwV34lWiwsazxUYrD5vPa4O'
        b'KhyoztiGTGp4f2R1FnquPo0NcQyqWy8K1pITKvC+nYON7gA7mwB2oAsadGGPEzxxkYmCyEoZml0jo6ZFuEZBr4+H399gPk2ke2bp'
        b'F+OR1ONjvNDLclXCHmAlrcyOHm4xnFAUq7WD+GsVrLCkjFG4TWcd9319SqLqDWqUWWy4Z+GYBdYw/+6O2KtpyhKfeSIM+wFLe3Sm'
        b'Ebm0X8wCPTKiBKsIdVX5sBMzVumEmTN1ZE5t9jPK5GGpe5j8plVsr0ZhtIfsGS1vxZEJIXZZoQfmNILwdVY6BB0IbVAaFvcflWo5'
        b'9YjXmLnui4ZOF4j4sW5tfBdoVLJybVGLKs40kZje1XHGpEwH/CaYICzXqVNLgzpiErWTIPik5kEIQ0eZ7xJpR32+1JuXR/lR3Skw'
        b'UqHZEjGH9ktmN8JkiquLrd3oo0nRLdCatqCfu8R7SRp4OdMbicMaPA704SLxrndMtd+qGx3d6FVHHTxeNLlQbq6jesy+tH5aqk5z'
        b'S7b21BSUZyRNENTctATfBhkxZEzI4r8dla65dqzgYeJgViL5Kkp5dKpuOcqD8hqK2VTePgF4Pe48VrosNUhunPjHbcgkSrdi3qPY'
        b'w1qLj9aM9KJe+2iF9JULpN5796W65jxcgiGFUm1J4mDlqrFtN8ATkFJ2JBF5R+p8bZUvQP533/9glFNNvtgamauWkql8bpKHeJX9'
        b'NacQ5rvuUNDCMh2kPCiE6qxObBpi4DbBPUEVCS2CuvNt3Rx3ZbLYHfrkXl5kWFAGXZ7Mzs4mfDuykx2cRW0VkgcmYyqwbqWeQMpr'
        b'1Qp5fbrKyjc3x3uPtffq07wUYExNCjSeB88emJMqtRnorxb8pi41D7wDG4BluDZ6b4bEnp8XBFmPiVPeP8tj9i+Ol7lJnAVfzAt8'
        b'dOiSbsJ4aVtvrObdFbpTXrv691RjUM9ngvmg4yqYzOtB96NyPseGs4FxBGrQSHI9KUcKWR76V+VJwUo2oCjDkZZtbY86MO8GqYGV'
        b'MxyUXuvxaWAGwfpui0ryGirqt8Pi8jqRqannLkEqw6/fXKvbJEXio8b9wGcXtQEnHe6iyryMwAsnqTKoPYUOreIqYbb0vZnWKFIu'
        b'uxmOneozVk5INFyL9kjEkZ/bDJOjlwIemm9kLumI/t+9EzuDdVXs1Rd8OwI303p1Y5kEs0vSzWY2UzlZVNVKYjZPMaRabaOlZr5m'
        b'z9aFXONleYGNT6CJD+O1y6+tln67Uy/dgUHO5N1wGP8fpv4fC1P/NwNT0xQ5C3rN9c5XVfeAyqhNXh9caVRQRt9V9KsKmABedHem'
        b'q/AHplhrVgSNkq+uELJg/Z8UPf1sHDjrMo5R4VS2Uy1sVXytneO8ZgHbkAxS6ei/jvRqjvJuI11iLEsX1UVFBXZMqwl3JHwGPgdn'
        b'KPt0QBOhIkG2Jl1HPoi5RjUk7DhXqV2hHJklw9qbfgN0QywU1CC3DbKkAr9I0X5A5kZtT9/n1h1gU2NJpdvLXzbB+asAuKktDnlH'
        b'1sfJxeRqeuXOJ3/9PJ1P8FYRF4xGXOVpasfwVtpcCdP3+yEl3HVV2rp5YSU1Ydo+xCV+sjSjWyMXp+6vkzl/FVOy2iiSjMopjQLM'
        b'jV6+pFiGQXZrssgOV1+Wd/V2T4sIQGcg3pQTEYYcP/dVRO3K1uPR4Ojw8MnSpJqfaVCjWiD+1hgxJoA92W0qek71XbJxwb/kuRb4'
        b'QSgrXV1F6/2Bgw3DhXagXBX8ljDWq+7mlQ6/O4puFBfUN7h2GwZqsUB3wFhtWX3U1I4Zu3qr2+GviT0aweYrbb8egxlcpehFIUNO'
        b'Og7atL46u9eo8ME9Bz16KgMMGg7zGzFR1jJkm2DgFt4GLxIH261cBfhN605/984fzv8ERpbLNIJkC2ZTW0sR5G/X+bJAEWVFklDe'
        b'wtFKqg8e6Ht6OrnIimWG1/8idW7BHDg1424Y/vXhzR8xdE67XwznqzK9vnk8UhuxXBYDV2zanHVYwYos5660cekq2FG18nucD2/9'
        b'kUYYdSvW9fKR+t4cUf3FfKG2I/QOYsn7lXMhEY/N5G+vi6s7fJAogtD65NPk5JfL2fRi4V7OJ5djwGGBG4VKVqtim2Q2KbnlWZNb'
        b'L5MA3niTYDGfXpbI7V5+/vlMf6V7Obk4nV58tL7WbydpnOA/h+CaTqC+hio/05u1DOgH/O87GC84/e+6v/bMGgwoTXfv5I6Dzf4z'
        b'GGMeLTWApXPhXt4RXJI0dgE5Nv742PXVPyBhvca7nszOz6cLrHhV9qLuv47nJ5+mv8KKfRhDhgP+F7qdXy46Dm2rVWgS4UCisTLP'
        b'2jY76t/iAlHHxFMKZWsHvFp5/Ka3v7DQWhF136RzScpR+lrJraeY2gJq2eUHgnTDdlT+GxrOON0UeJH3kt5gtOYDaBN2uO4q9l23'
        b'b4x0vBVseTUEGPLVd+P+bRz4YJ7XlopVrArUMY7ZSwFviOJ+tsp/v2JlpD37hoBb/roBRcRXZUEf+KEfwmpUeKH17ChZ9z3WC2Lg'
        b'SnVzhdfF6ONIGkl/4Vh9+b/6OHHU/GSK7kQqyCtDWL6Xuz+m5zFY76LPtvGJF4oqDXpV2NJ1aNmGAYOO+tlyaNyB48RePd9SfDOh'
        b'Ci6QdwUXbai++nx+Pp7/rYnUPKoDuXq9AD8Xo4MNl2RzXTR211V1cLb83n8D2YkEiXBHAAA='),
    'data_static/research_dataset_registry_v1.json': ('1dc9e4ba5f779d2a01433cd94e675d4fa60b2797821f6cf9581faa30e671eb6d', 732,
        b'H4sIAAAAAAACCm2SMWvDMBCF9/wK4bl2aaEduoUSyFBaSKZSilDksy0iS0Y6h6gh/70nubabpovBuu89vbvTacFY5mUDrcieWObA'
        b'g3CyyUuBwgPmDmrl0YX8cJfdRLa1JURys9qulpvnNX97fXkfSqBVrXYaeGUd96BBonXEVkJ7SIQoW4UIJa+c/QLDazDgBCprPHEf'
        b'nwnytncSeCuMqsAjl7btNCBcOP3ki7IT/ccTX/S+6JyS4ItSKB2m2kWLicgTMDaVCDhSo8rUXJK1tjXfQ5h4OiSDKdM/qs7ZspcQ'
        b'+83QWu1vd73SJXfQaRH4L5eiC1mSn+l7HiY3uihzAENTC39tYr9jsmhwKatob40B72lYBp2QOOtdbwb1NXRtpNq2RxF3qMUeZhNt'
        b'qdgQRNFSaZLOK+SqpOwKU/btenn/8MhsxeBIN7GLh5XPIloBG6fKdgHBD7bDvIdtcmd1ymKIFz021ikk9QGYhlrIwISU9NwGR5ak'
        b'2eK8+AaFCOZv3AIAAA=='),
    'docs/research_dataset_generation_v1.schema.json': ('f5ed343b1148bf4f9037ce6085ea8a8fd08d6756286ffc6cc6a78274c073d60e', 8914,
        b'H4sIAAAAAAACCtVZUW/bNhB+z68ghD5sQB0ladd1fctSF8sQJIXjbC0KT6Cps8xGIlWScuIG/u8jZcmRLFKW3SRoXpr67nh3PH53'
        b'x6Pu9hDyXkgyhQR775A3VSqV73z/q+SstyTvcxH5ocAT5R8dHB30Do/8Qv6lWayoisEsHYAELMgUjecKUAQMBFaUM/QL4wpJngkC'
        b'PhDOeEIJwmFCpdTsXws18zTXwsdfgaglTcC3jAoINf2L/q0pFcP6F8Q0ouMYggkXgYRYL+SiZBIBWEEYYFVSli4EImMBDUtiiBWW'
        b'oKSnf45yq6ngKQhFQWq7dzW75W+jnjOpjMOi2HbPaOrdb7s3O/Ry4UWrtxaVExxLqC2t7KUiX4ZMKkFZVGxI07X+JJc0m4OeognU'
        b'PakHooPGhLIzYJGaaubhPRXfrqhHBwc1E6uwWrRjIfC8pvxUQSLXdZfEV0crKi1IpUo7bgpOAz0FvXDtHgMFvYatkpZHqk6b0Bik'
        b't6KMKiYt0GkarXOqUArlfib3U0EJyP0Q03juVSQXNm/dynI1vVzLCopWRcstNhQ5A9sW3DIKMxqCWFujObF2iUloMjDRW5ZByrXE'
        b'vMkmMda1YkJJnlmW5WUxCaTSkG8KrHIvzUTKpT6fhkhKVb46s/AI16t0WkOAiSrN2ARjOgEyJ9qQS0IHJ8wIiIDwUEtNcasIm9DI'
        b'CB399qYpV6YxEKCpcooJfBMUoi4RPNMwwXltEjyx7T825apaTavBvU01FKTh1VijNcw4s6OOmibPXZkqEtYaVeVbqpUjJ2pY/Unc'
        b'qWfIT+LUWl5avQKWJZYqkfMG/eOz4PLianDSt7irBU4uzoeD45Nh8OH00/Bq0PcaQqPNkVsrDlYvV2Vz0L/sHw9O/gr+/DzsXwYX'
        b'52efvY0mmuWl9YDqDbB+Po1WWGFnjH7LoJRQIgOLULNHdjsM06SoJHwGYm49DHR/13HxlcCU2bGX88eYXCuQyrOwRw3aYmPcKzV7'
        b'a+z90x+cfjjtv7cD7+PpMPg4uPj0eRfEudpFO/JWDnUoTWtd5qEUN5vTjoUmxUqBMBXB++8L7k0Oen+M7l4fLF5s5UO1+z2kI29e'
        b'd3HE3l6f3o9m/36U4tJaNzZucJstdsnstRvJjlF3TkLt2Vu57Dyl4co96hHN7rl+LSxTjnMqsKGsBWHVeU4jeI3pgl77DNI+hZgE'
        b'1vM1jqAlUBaO44psmtdcWeYG4wW/sdJ1cRZWG8BCG1kDL0uYVRXVpVxkCbBG6xzZCqj7ml0Jy05XBNP96QxcDT7G19CxubfBdwfH'
        b'zINV7HIr+k7ToFUixUJfrdTuvreU5keon054brBPmYLIMpmX6UuTPMaHdj6+Lflv3/7++tWbt50cy9PjgfzqdhR53v3ASdTLaLfw'
        b'm5x+YpNlvXCYLe9/d3bE35eU5aNUm3v5My+5zofzDXJ6+MlnrXA5ai2345BtNHnPdCx9fEnqWqJLW54hesqiSheiQBeFsQM4WnxK'
        b'o+kW4jG/2UKaxDx/H+gqPzPnlS9gnDGIcHWNZcmiEwoqrWED/hxddHMnteClHSUOboLFNSgnlxK32gS+c+YEEsGxzj/sPqlMCGDE'
        b'Odfi8GsmVb63MZZUWtuAvWi3N1trptnFuhWKLs84nR5znICqZ/sz8LVAVYuvq0n46tLbTrWG5DM5ryJBnoW3q3R9Ht6WxaMbwt5v'
        b'B7FG6Wmx0noDXj6oHv/rDJVmX348Ox0Gx+//vrocOl6+CsnhxfD4LBj0h1eDc88hNrJvdOdOZoaH4BrmP3KP2giHjVBY7Dgw596P'
        b'KQuNbw/4NY3wJKHurzsEKxxz90ciuAWS5Y+Qaw9ZP/Cppu7S07+Ire356R1wBvXRXXGDcW/9f8u/5t98A94Lc2zLa6I3yJhpGQiH'
        b'ITX7wHE8R2QK5FoiLmhENQXhGywA6Vuupr5ERHApexMKcahFQhAvkXkjQlMspyD9fPz0zValT0Nthqq5by7/PuHamB9maWy+E4Ff'
        b'TAgor5nmg4GSCLMQwa2RoArpQVxob8yXCBzBPjrDIgJf4Bs0022DC2Q+piMqEQMtsnQbQkTZvre32Psfq7xJhtIiAAA='),
}


def historical_reader_fixture_bytes(name):
    try:
        expected_sha, expected_size, archive = HISTORICAL_READER_INPUTS[name]
    except KeyError:
        raise ValueError('historical_reader_fixture_name') from None
    if not 0 < expected_size <= 64 * 1024 or not 0 < len(archive) <= 128 * 1024:
        raise ValueError('historical_reader_fixture_size')
    compressed = base64.b64decode(archive, validate=True)
    if not 0 < len(compressed) <= 64 * 1024:
        raise ValueError('historical_reader_fixture_size')
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as handle:
        raw = handle.read(expected_size + 1)
    if len(raw) != expected_size or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('historical_reader_fixture_hash')
    return raw



HISTORICAL_SEC_FIXTURE = 'tests/fixtures/manual_foundation_sec_source_v1.json.gz'
HISTORICAL_SEC_SHA256 = '245d34592e2ae3cdde6f72c732426698e3bffe9099c9150c88c06ce982d590be'
HISTORICAL_A3_FIXTURE = 'tests/fixtures/manual_foundation_a3_registry_v1.json.gz'
HISTORICAL_A3_SHA256 = 'ee45321107da0e45a51966805838c3db6f2fb5b99e04026a842a669006c38aab'
HISTORICAL_A3_FILES = {
    'research/a3_candidate_packet_v1.py': 'c477f7323814b2f980449da3db6e238b8416c5644d151bda4e3e4790eb3b003e',
    'research/candidate_registry_v1.py': '9659fe6afa3f6a85a7524fc369bb984ba22693b3101ecabe9daddbff413e47bf',
}
HISTORICAL_SEC_FILES = {
    'tools/run_sec_ownership_signals.py': 'a81c210d64945f236cc64e8bbc5af3b85014c963b7d6dbd8acd9ec604b7518b4',
    'tools/run_sec_submissions_collector.py': '81113d1b6b37014f45f9db711d04657342eae64291f6ba2761dd21b5c21e77a0',
}


def _historical_lake_archive_bytes(source_commit, fixture_name=None):
    """Bound every archive read, including the generic setUp dependency copy."""
    limit = 64 * 1024
    fixture_name = fixture_name or HISTORICAL_LAKE_FIXTURE
    if fixture_name not in (HISTORICAL_LAKE_FIXTURE, HISTORICAL_SEC_FIXTURE, HISTORICAL_A3_FIXTURE):
        raise ValueError('historical_fixture_name')
    source = ROOT / fixture_name
    try:
        before = source.lstat()
    except FileNotFoundError:
        before = None
    if before is not None:
        def identity(info):
            # Do not compare ctime: Native Windows stat/fstat differ there.
            return (info.st_dev, info.st_ino, info.st_mode,
                    info.st_size, info.st_mtime_ns)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= limit:
            raise ValueError('historical_fixture_size')
        flags = (os.O_RDONLY | getattr(os, 'O_BINARY', 0) |
                 getattr(os, 'O_NONBLOCK', 0) | getattr(os, 'O_NOFOLLOW', 0))
        descriptor = os.open(source, flags)
        try:
            opened = os.fstat(descriptor)
            if identity(opened) != identity(before):
                raise ValueError('historical_fixture_size')
            with os.fdopen(descriptor, 'rb', closefd=False) as handle:
                raw = handle.read(limit + 1)
            if (len(raw) != opened.st_size or not 0 < len(raw) <= limit or
                    identity(os.fstat(descriptor)) != identity(opened) or
                    identity(source.lstat()) != identity(opened)):
                raise ValueError('historical_fixture_size')
            return raw
        finally:
            os.close(descriptor)
    entry = subprocess.check_output(
        ['git', 'ls-tree', '-z', source_commit, '--', fixture_name],
        cwd=ROOT, stderr=subprocess.DEVNULL, timeout=15)
    metadata, separator, path = entry.rstrip(b'\0').partition(b'\t')
    fields = metadata.split()
    if (not separator or path != fixture_name.encode() or len(fields) != 3 or
            fields[0] not in (b'100644', b'100755') or fields[1] != b'blob' or
            re.fullmatch(rb'[0-9a-f]{40}|[0-9a-f]{64}', fields[2]) is None):
        raise ValueError('historical_fixture_size')
    oid = fields[2].decode()
    size_text = subprocess.check_output(['git', 'cat-file', '-s', oid],
        cwd=ROOT, stderr=subprocess.DEVNULL, timeout=15).strip()
    if not size_text.isdigit() or len(size_text) > 8:
        raise ValueError('historical_fixture_size')
    size = int(size_text)
    if not 0 < size <= limit:
        raise ValueError('historical_fixture_size')
    # Read the same immutable OID only after its size passed. Cap stdout too.
    process = subprocess.Popen(['git', 'cat-file', 'blob', oid],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        raw = process.stdout.read(limit + 1)
        if len(raw) != size or not 0 < len(raw) <= limit:
            raise ValueError('historical_fixture_size')
        if process.wait(timeout=15) != 0:
            raise ValueError('historical_fixture_size')
        return raw
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=15)
        process.stdout.close()


def historical_lake_fixture_bytes():
    # This is an immutable positive test input, never current reuse evidence.
    compressed = fixture_dependency_bytes(HISTORICAL_LAKE_FIXTURE, 'HEAD')
    if not 0 < len(compressed) <= 64 * 1024:
        raise ValueError('historical_fixture_size')
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as handle:
        raw = handle.read(64 * 1024 + 1)
    if len(raw) != 53726 or hashlib.sha256(raw).hexdigest() != HISTORICAL_LAKE_SHA256:
        raise ValueError('historical_fixture_hash')
    return raw


def historical_sec_fixture_bytes():
    """Exact33c originals for temporary historical positives, never live reuse."""
    compressed = fixture_dependency_bytes(HISTORICAL_SEC_FIXTURE, 'HEAD')
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as handle:
        raw = handle.read(64 * 1024 + 1)
    if len(raw) != 30665 or hashlib.sha256(raw).hexdigest() != HISTORICAL_SEC_SHA256:
        raise ValueError('historical_sec_fixture_hash')
    files = json.loads(raw)
    if set(files) != set(HISTORICAL_SEC_FILES):
        raise ValueError('historical_sec_fixture_paths')
    for name, value in files.items():
        if hashlib.sha256(value.encode()).hexdigest() != HISTORICAL_SEC_FILES[name]:
            raise ValueError('historical_sec_fixture_hash')
    return {name: value.encode() for name, value in files.items()}


def historical_a3_fixture_bytes():
    """Exact71111 originals for historical positives; never current admission."""
    compressed = fixture_dependency_bytes(HISTORICAL_A3_FIXTURE, 'HEAD')
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as handle:
        raw = handle.read(64 * 1024 + 1)
    if len(raw) != 51946 or hashlib.sha256(raw).hexdigest() != HISTORICAL_A3_SHA256:
        raise ValueError('historical_a3_fixture_hash')
    files = json.loads(raw)
    if set(files) != set(HISTORICAL_A3_FILES):
        raise ValueError('historical_a3_fixture_paths')
    for name, value in files.items():
        if not isinstance(value, str) or hashlib.sha256(value.encode()).hexdigest() != HISTORICAL_A3_FILES[name]:
            raise ValueError('historical_a3_fixture_hash')
    return {name: value.encode() for name, value in files.items()}


HISTORICAL_FEATURE_INPUTS = {
    'r1000_features.py': ('899d4ccc495cb9c66afcb06093f854e1a1b90e35', 297268,
        '96decfe3eef4bfe7fc92e2419ffddf9d1ffc54be685c98d96f270a551cd568da'),
    'r1000_pipeline.py': ('af9234babc4e713d57daec3ce7df1451c0ceae7e', 950048,
        '8384a59befc11ebbb80fe9235e40dadc6fddefe3a8f2cf6adebf47621d1a3880'),
}

# Exact public tracked code only. This is a bounded shallow-checkout test
# fixture, never current code, data, provider output or admission evidence.
HISTORICAL_FEATURE_PIPELINE_GZIP = (
    b'H4sIAAAAAAAACuy9/3YbubEg/L+eAofam5A2SUuyPUmUcM7hyLRHO/rhSPIks7r+OlA3SCJqdrfRTUm045z7EPsO33t8j7JP8p0q'
    b'AN1AN/oHZU3u3T2rk4ylBlAoFAqFQlWh0Ov1xP7e3h7585pGGZlFCx4xMhqRhCcshN9j4S9Zmgma8TgiqzhYh2y8s3OZ0QUjr0n/'
    b'YO/gu9Heq9HB3uCQzNdhWDRlD5mgfsYCMhfximBHXhYnL/c8HqUZz9YAk4bjZLMTrAWPFuSCzamfxYK8X9KUkemYXC15qrol8X2U'
    b'Hu4QMiIfIn7HRMrIczJnNFsL5qVZLBi5WfMwYCIlffzNW6uK3iqOsmW4GcoantVqgDBPT0gmKI8Ajz7+5t3T8HYei3sqggF5Tm6o'
    b'f5uxNCN9/ZuXxCKbxyGPJYwTiuWC+fFqxaIAqZYjE2KpVyrVKKnSEsSjOPJZBPRnAVkIHpB+ykLmZy80Di/8eJVQwTzfqFqA8Z5J'
    b'QJchY3ds5NOEJHHI/Q2R7XgaR6S/YBGDhjmwFKt7Pk08WT2Hk9EooGEcMSLruMiS5pU0oCxOIvJc9cmEIjn1RUwEW/CVMXUBmzMh'
    b'NNtITnsZjDgf3WCr2QMMjjwnYh2NaBiWeLTPsNyL11myztIhVPNoGMpfAjan6zDzNJdKRH6mIZfTQfp38nek55wvZDPgbE+V8Djy'
    b'0jXP2GBn53iFuAQ89XkC8HZG5Z8dQohifglxnGzgEyGkn6wFIwHN6JCkWRDyG0BH/vw/RrslCxMm0ryhbKe+Dkm0XiWbFwmQPHUD'
    b'UOyeQ+irD4Thimew+NwtU76IaGh0rSYdJjJOORBjSHJmI34cpZlY+/DdDVATPkfl6sfjS/L2+GQGcseaymG+IIc5kw1zoI4fOfND'
    b'UkxUPvtuZNzSiJD+2+nR9A1iJNhIgk0Ju2Niky1BQABrNmGif+wxk3kscCQgUeRayAY7O1XCrOiGcMlahuyU7ENe2FxBXuzYk5xX'
    b'UHNHbtYZOZv9PLuQwLIlIyvKIzX5ZE59GrDxTq/X29nBGp43X6N49DQWNIriTMqrnR31Tf4T8pv8Q6x/+3saR/r3MF4seLTQf65o'
    b'ttS/x6n+TTD9W7pcZzzM/1rfJCL2WZrXzPgqr/uZJ3Me5n8uabo00LmnAngnlWOCVeaHNE1Zmg8qDbifDYuiIZlzFgZ5Awad6drw'
    b'9zD/KuskNIMedZX3xtgS7t+Gqlq2SYBpVMk02gzJG+z5OGOC3oRsSE5pAnWG5DyRfLizk4kN7HZEzppPs5s4TjXZyRHNfoC/jwBx'
    b'PudMDPNvFzS6tf5mC8HSNBZD8j6Owx324LMkIzP8h8fRISG7RQdRnJE0E9zPwg0R7NOagzCmec84fMCrigKZlHAwP2gkyASxIBNy'
    b'BrsI2QX6sEPCF1EsWGnY6W3IqIjGiWCKEQxKyr1IBJc+DZmoDgvB2JXqetXThrKU0JREST6TKFjhW6JYQy6vkC2ov/F4lKwzb7GG'
    b'Ja25NqOrxMuoWLDMU1urFJQizpif6SLc8obkXvCM5etfFRYr49OapVnO/5s5j2jkM8BnM9+xiATNqfBWccBCjctJvOBpxn1FfkTj'
    b'ggcLg9DWOL0VFbcs84BaQDcc+MqnDq7BxlCkiLqzs1vR4NT+vU9LquL7H6eXs2fe0fnJh9OzS0NXzOKd3cp2iRveCNYpuV/yjIU8'
    b'zeReQ6MsHYzJebZkovhCnu/sKm32SArNNONhSEIO+goL4/s/ghjckBVfgNpDeKQRvXnhvwjGO7vkkjFyMXs7Pbo6v/Den0zPxquA'
    b'/H//73fEXzL/FjF4To5+nJ69m52cvyPF6AgoYZvxTlVyK0L3kXBIgQPv+OzNh8uri180KYZF4WvvZDZ9M7vwTqbv3k0v3jiq7HvT'
    b'k/c/Th0lv//BOzk/e+ednJ//9MP06CdHlT94Ry+9qw8XZ9OL8w9nTvD73umHk6vjH6bv3s0uXBVeeT/+8sPF8RsXHpc/nl9ceReX'
    b'3tXF9H2paHbkzX4+fjM7O5rZJbOrt96P5ydvjs/eXdZV0V/ffrg8Pj9zofW6li77v/Nmf31/cl7X8nfexezd8enMu7yaXpU6llO2'
    b'5139ODudee/PT46PXPN2sO9dXv1yMtOQrBpHF8eXx5fe5Qz56ofZ2ezt8dHx9OJ4piucX8DIzt5MT2dnV9MTu/np9Oji3Ht/cXw0'
    b'866Oj36aXVgFby9mb7zLmQHt7Mx7O5teeO8uZrM33oeLE+f3H5HRVJuL8x8+XF55/8P7y/HZJTB/6fPRyfF7s1PXMGXJ8dnV7GJ6'
    b'dFWh9Ztfzqanx0eawe2m59Mr7/3F+V9LtL26mJ298a5mp+9PKjNzOr34aXblTd9M319Nq939MDs7+hHqeBezk+nV8c+l5moEF+eu'
    b'xidQffbz7OzKm57MLq7sUpgp7+rq1Hs7PTmpLrQ3s7fTDydXQOurDxd6Vt4fn5xML7xLnOsKuGLif55dTN/Nqktn/+Xb6se35xen'
    b'L1+9LiE/vZpdXnnnZye/eJfH787K/GSWT4+OZu+vppX1Nj26+jA9AaY7vzi+Ks3K5cls9vPMU3JSERKFxvuT45ylWmp5RyfTU8VT'
    b'l9Or2cnJ8dVMIqUIV1lEV8dH0xMkvJtMeZWfpycf9Kw6K56fvr+Y/Tg7u4R5bqf/j8eXV+cXCNqsfDL7eXbSqabcM7pVnb676FTx'
    b'zx+mJ5WpqakrP5fqvj2/+AtsMRcz2BDah/5mejV191qRX6fHZ8enH069t8ezkzf2gjuZ/jA78c5m0wtgQr2CVJ1f3nqAxcXxG71s'
    b'lJTyji9/hBaKX46mZ9776dXV7CIfzOWbS+9q+q70pzc9OZ5ezspfj6Zn52dKTgBLFe1Ozv9i/Hk2m72ZvTE+/PIWKHBxNbs4QRp4'
    b'p1PFw3IloSiW67JYpsD/70B+vT0+m54dHU9PvJ9mv/zl/OKNo87FbHriTS8vZ1eNlS7PP1wczcpVYPpUvRyxX94WCsfVuffu+OjS'
    b'e3dx/kEVz87eHZ8BxA+XM+/n2QVskkr44l7jXcxUxb8enXx4M/POpqfqy9H08kcltWXdQjDBCpue/QKL/9I7nZ3+YADS9pgVjdY0'
    b'9KQtCPSlAG0LLNAGpBVNVNeGWjfcGTQonQdlpRPNJnC85NlGm0/IKr6z1c7C2jKuVwKl4ggGo1gETJA0Ywk5sJQ+3YGl9XmCpXF4'
    b'xzx5+PbAFMgzL11SawaOzk9Pj6+8yx+n8nMCA/N46rEIzouB/BrF916Wyt/DeCF/oUkSbrw5TTM8CMiPWez5c1VBKqNwvA+hUuRt'
    b'GBWpZ1tY7nmUxoJ/Vu1FfLNOM++z/Cv9tGbsM/NSJjhT/S+pCLyURjzLG6V0zrx5GFMF0xdxmnopQ+sQTLYFtK7Uu9ng11ioQa9X'
    b'THBfde7FQtv0NKZhyKNFCbiI770Vo5EaHOOLJVhJtZVTGbMU3qt4HWVeIPgd8/jc8+OQ3hgjWt0GXOFCk4RFgbfkYEfeeAkVn9Ys'
    b'M+oKRgMPrCEeGCrKBap+pWwdeVl8yxS2/loIFmXegmeKXeR3aTaGyjxgUcazjUJK+EtAHUq0ERQL4MgJFoucYwAFwe54vE49OBp5'
    b'kjD15dIULIs1hQXLhP60zLLEg254FDFFI/1Ns6xY0ZB/Zl7GfTBSyBNoKo2r7o+J4D7z0s3qJg41avEtoHTLvCiOgCixIlby4PnU'
    b'XzIvoquC9zdzqzla3qINCI1UVS+moMDQ57f7e46PHhz+XN/N9SDBItUK2MbHNKMZW8G8FsU8x0awdCm/sfkclsQd82iYLKl3RyMQ'
    b'bp5gWElRLC1XVt6EohfBEsrFFtUl+IBuVGW7+4SuUxAAIKlTEMPmaZdGgTShhzQqzG0rmjHBJbXkgvYECyn2n2aCRYts2SDNX5al'
    b'OY+CdZqJDXEYs3d2c7nuMIH3JeQDcnFJnpPz354xHpKQUXA/LHlCnoPdcaTh7+yqshchXSzAzPOcCGUNHXTaInBzeGltDrmx1t4d'
    b'AgZSyrvnYGb2FiJeq11P/o4yzMtiT8T3alaCwNOIVsnpqqMwV9bhoka6vilqyQF7asDakuxihHxll9kTbebeXOTrkGYZ9ZdFHyuW'
    b'UfR95GtynTGP+hkoAongseDZBqTvehWldqV5CDtftkJCef565c1pGMIOVqq3jgIK/ExDD0iSO/5K8BT7I1jJfO5+5XJuqLCKaeYl'
    b'In7Y1PQUR4yHXsFrXurHgtl1UiCgWiEhvWGa8D7uS4lgKaxQq39tlq7bFecs85clCcKUfdxjacZhcab1deM7Ju44u6+vUYiONKJJ'
    b'uoytniXhitlIgRBmhc28Wscul2ZP79OaioyJcFP0qCtyAeqMUg9grSku1ApKmtPujoZrZuxyKHXVRs3nHo02RmEsvG0GvKIJjCZn'
    b'8yw21/GKiQWrG6ostBnV41EW5+7r8h4KyqDNCXlh4GIhJIBAxy6OGP0dqkyL/Brk1AZS2SmqNVW/t2xzH4vAW9FULcsqyTycFboB'
    b'Qqs6sJitmZTDK0oVBrpYSZq8fEVBbfWWMXiTJYXKZTxKORYKGqUUFU7VfjNXNI2Fx1aJVqk28aaxW28esgcO7UKqtGzPpwshuTD/'
    b'hp7/XDB5CY1Y6AUMFM3ALU/YndyM8VRkSxRFZR4F3Ke5dpwLInCtA+8wsKuDvHfLI2XtT7NNyNz9lGrSgCZqB3HXCzYRXXHflHF2'
    b'RVxU6ryH8hKEi+CBLpcHGFVB6itYJcxVEd1VthSMeSG7Y2Hd3qer+oKnXB4vYD1rHToXuRg2sdh4N+GaJYKX5WtOhHWY8YCvWASe'
    b'FNineBhSIaV4uS6PQGhG3FvFwPTrlR6GrLerFJz9V4Zi83pwSJabGwj0QHFjQRSpR32fhcqf5No7lvvYSRqHgZRyzkrflWbJuQuB'
    b'lDtAaOwh8xIW0VCvh2IC2Ip58nBqT/IuuVzGIhtdXIITP9EjfD3afzk4JGkScnD1xiJ7EcYQ+AOKmA9wRuwhk9QlqssyCbCZB82c'
    b'ZJfFORRP8PTWxn6XzO7gyOQzoiYEeRLDhjSaqGFezo7I/su3L97GYkVekefgnCAgWNCtnPNyynyPKYj2FGMxy+YojXCvtYrzVf6Q'
    b'hDEiC0eakC/jOHBNiVqfKEY9v3D82py+8XEp+9DVxgWGJakHxzrs0VVOYXuVcHg0h2ijuprg6YItGSwqrgqr0MuYv4y4T0OPLgRT'
    b'4t/Bbqb6CbNcraLFth+u04wJD93VZkUpOZAd93/vewuQ2LD/KiUUbUVqzf3eOE28hLkG0D4VwK0BI3+P1wKCQcjVkpFlHN9KJ226'
    b's0vUkfoFVvRUxRfSW01DONdvRgrjoIiN0gzwRzKnPIR1srNLqGAkEwxju8DlHEejOc1oSNIYXMWBjKMhKwbe+BSrg3P+Joz9WxZY'
    b'5wkLG/tQofRuqcN7N4LR2yC+VxvqAttha60iwC4PEwt6JOrX7IHrjQ4MWjzNCn5Wpg9zh914AV+gIanJOPeqfJyrBhahF9cdW1Q+'
    b'3RVhShZVdASMRQ9l9JG2Di/c90Bl0hu0NM7phaZMjyD0k5Dn52Y4LsmBI1/DISZfBM5to4jGyy1OjloQ+BalsIetYKhMFIc1p9io'
    b'QDXNMyWZUdT14ygTcXGmkNVuWOQvYYv3bhjNwIA2j/11SV6p9VWAyg/6sNTAkJGVpZHeZ9TG69MkV19ArmBcoOQyra3yVc5t/jKO'
    b'0wKGiprAY5A9X7qGmlNf24ozsY58QE0VYLyP0tILY4QqNI6qykAEKqxl1AlYsE7ggIY2allHxPeW4gJLQ8dMOqinpkpKzkDweYam'
    b'KoMy0q6nBpsTu6z6I81MYinwkooFITTm3IcRxivbxicb+TRdejfr+Rx04tiuIVFUn8AWmzDB4wDMfmuhORh+hbFqK1fi2V9yrQXG'
    b'CVYlloTxBrYC57pzmP+1jlgyNSmlVGkxKqBNrXa1QebGjIwzsbOjo8LGklv1n/2eDATqDXZUwNp4wbKTeLFgot/Tp8/eYJyy7AQU'
    b'zr6uph2NbQ0TEScU1gmZkLc0TJmr/lqEIb956ernL9OLs+OzdyhTVaxKMOIlIepy4JRlZR5WM94pYFV8JfWOCtCDyl6Kqr3NiFnt'
    b'CzaScyLjyMDgSbI4GTQiUHZ51HdggnHQpHBd2W4rl8tqt8FhVUtH0q8ZnQ3ohw8nP2lopxAQMz36cXaIK/M6zcTQ+C3NxMePZEK+'
    b'fN3xjqZXP5yfX0LYwen787PZ2dWlbqpjBa+LltNogy1lPJZFljJdtnG9VefXHH1GeIphpRqk3PE3GO9q+ut2dmWE5R8hrNZFNGwB'
    b'kF4SH0K7wSkDoGmmFANGeAaa04JC1C5Zp0yM0nUCu3NA8oMkclYxeL808mbvM3luuZ53dsnzsueZPLfdzuR54XN+obzML9CvTJ7n'
    b'TmUElPuUyXPToSz7rHiTyXOHKxnhmA7gZ/C37e2V8Nyu3qrHs5AIRAW0o4ppTQxPIUiPRQFMmO/HAvS/cGMRumKi/71hpF9H0tBC'
    b'+vUWst16I7HbNu60i++2WcVbrbG7nS3ijcb1QaMbwuZRxwK1AhjzIOUGcQ4HWyY2JFujyCS3UXxD+mjqI1dXJ+mQwI2WkbrSAj7e'
    b'AJQXrXrn+35+ShqP/0CyeLEIWQpEK19FyfW/dEim74/JLdukAwyyRHEgGKBU8kf3BzIAExiKKid8zhxkBDbCTQrxmBii3lebA5Hq'
    b'kL2uD25KBCt11W3HqGw80qtOnoNLvSOIMiLS3f7Ixi3++WaoOwGb450HZ1t5APLni9LeQf5hMZveQJTxE0CAuy0jE/JafnumHIhR'
    b'AKcfZoCDrctqLq9SgccWsJAIGfV5lNn1BQPPInuAqOVo4VGRcXTUGm1u4jgsN0rXcMqB2jQ0L27VNhuQ0ffE3jhlRLM/X3jxzd/J'
    b'pG0mJDVVE4lHTq8J/rf4qCk10b8URS4CTVwfZRN5k4XPawkFKwvMBDBMOSJjVOPaVhMC9OnXlRvd1pG6rePadnnXdTVk52G8KEje'
    b'u1hHeFdPBXwUphYp1kgvrzrvfdFIpBkVGdL/K0x//l3PylerWV+CUlPyBf/5OnRPWA7KVfp1IMHKccijk76Z1FcNB8biLd9S63de'
    b'sh24WgonACnRMQdJJmRFH/o8yjRaY41LfrkPKw6GZN8xK/PetTwoTL5UzghfP5JrdZgACzWPo7ySdV75+tGYhHyaFRqlO6agDOQc'
    b'4Jj4vpocc4xfh8VqrDLA0GpftxqKhnU1KoDqeNsEVVenln/a5RJALssmkxoOEVWmSYuoamL8omktJdsIaYKopWE7CbXwNDbeoLTx'
    b'HvwuDwrsGzFgQyvsa7cu6MuI63o2LAdyOYO4dl0hXM7wLSN0yxWW9Qxg2fFYlVisauRVEWCF7e3IKTtqygxcejasxCntGpFEz/LQ'
    b'oWfDppihQWPgpXWqKCtIB79HbXiEXnm4Al54oMGcHgXFYWNnl/RtJJ4Nwcn7TIYV4PXZbo7t3Qb/eKd4k13l3n9WfGuI+Bh0PTi8'
    b'LB9u60NB8P61I4QED5R1cQMQDFX156ur3DUxMQiwJaDHhFAbfWMBcsTWtBEJ9lN5KFB9xBHYSKUnBK/s9YP5IUmC8Rua0bdgAMYN'
    b'1Pwgt09QUoL52I+TTT9XhYIxxgiQWJCeYDc0xAgVmIAeKkI8IsFYDaVQiJT4DpQsV83IBHrNYk/PXz+4LgP9OCRMiFikk54fMwFm'
    b'xUIrUzXHUZxFtD8Yp+tVf0AmE7JX07UiSQBqfdEctn8JVQs4nG+jCvlT0RQrgs3Gh8HWXzYpUOBz4jcQB2l97YM6EyXjiEZ5STAO'
    b'Y//aRGpIyvX4HCYCxujFkQdXV7ONl8umXt2ExEzyFQCriy7uB0PSy2v2hqrbQSN+TcgA6jm8StuP5k4fKFb24Zqni5XVkB7PzNtP'
    b'4TbT97hpQf5vJN/jJqtEVDDggNXHEt4rHvEVRCKFdFEl61AeoU39uzOlg+tepTcZhaXFMg7NKahhWC3Xa9R0QrqKBIxFk24dfj8h'
    b'Sucfr3jk1TXQt8EHO8qHZ24Uk9o9pK8OcDqGT0kUx77St2PWWi7M6PmE2II0ZdkjATtu2WjIabwWj0a4cjHHJhsN/g5xDEFpNuRG'
    b'cIks3d8bggWVPUyCMf47JAFcW5/wKBs4YalJLyCgq6kGCpy68x0Ej+ALltEsE8AIQ9IrA0cvr3LH9IbkSqzZYFAsWDm9oHcXQ3Hz'
    b'sS0vCg0ffq6tv+Cnh5Ob9obVkpDTG7jOw5mzOEL1149XDKKFXTVYUlfSIHtctWOqhU218CaOb8E6rbyVtfXK9LYCa0oNPhZ/FnuQ'
    b'sRT+q0yBgBDGNcThuMncPkVp7RTN/fmmrizgGJGVu+JdNHwqoisp8X8OyWN//hiafzMpWyVjc4XxPTgd+v8095lhVSw9eX+lHWjo'
    b'WIe/Qp/G3jSsMGF9f2qHcH7+hwqR0j/Whv0b0q9KeENxqOKtK4NKIUcxKPB6GgzLm/9vINqgIgQbsITaqv2viaWpSCCOJZnRiKFu'
    b'7EZQ6gGosklFmEyM7uWhUmnKcKaUi7HuKKnVdVnL0swLQ2GYMkPDkLp1jYqB1z8l6FzTMHHNj6s02vQNXUJb8GTdeRhj3iA4nNoM'
    b'CuBLWovRdJ2ZAHpDsjfeGwyGDhAWTp8gGyIPWX9v/HurvhwCjL8NUwm1x6O5Iqyuhj4lsZIXwyb5xdRiWPZO0G8+4+j7ASrGXwla'
    b'HCb5nuyN9/cGY5rCTPTlTAy3ge4KEn866GCxzqMOv1uZgL8J7ipePSW4lIYshTCD+2zpbWLjNClhv/4W4OYZS4oCuOlq0XlC9sav'
    b'vm0EzdtyFzoZu7Ve4HJNQxhdGNE+NLb4XK6+Jz2O2KBbDiNOPGzh8c/8mGx9/g35p0uol+r0tz1X2wg5ZbmC/FQs83i4gmkVc+MC'
    b'/boC2indvtdisDp8sx7QokoEa0P7fuISs+VdWiUt/NdK2G9b/20S9tug67BYdDxU2eSb4f8fIsGbYVeOOd+4PCvw8mViSzvFzffo'
    b'vvOcYFc8QqAvD0rr51cbUZ1g+PZBmZDzcX3XdVzd9yd1uel/IxmhGDeO4JCSpyp5stWRiHjOM0368n2vJ+umuAZWXLF82h7wZhOq'
    b'/CxbJ04tZ6cLj0oOkftUDhP26wLS/uvB4MkE58unk3SPF8j/WVLOJHajjNv//dPLAiWNIED4oTjRF7RwKIhtyuFvSqTsoiVaDZTG'
    b'2CQ2UXesd870huSl04JRxu0pp/iJN7GnQLrTXvX0+1Q96g79dHtcypozIvCqSjtzt/uvz+CmGGhn74P/Kuz9OOn1n83cdVi7WPvg'
    b'VSfEq1rVtog4+fpltXf5XxoIT1pFLX4O4C5dv5e/+iGr9IaGAaLXq7E+xDd/Z35m9Ke3i55hGtV7TpoZp89xmokxXKuFO0n9Hg3A'
    b'0ujTlE2UtSOi8reSHdRh4oBxLcL4BizYGLam8xo1WDqgTas+6/YxPfE5rCPI/YOnhfloracL7PLlocdo4B36kTnu6E2M9+1e7/2K'
    b'wA/2nha6DHTM2CqByCS92TxpF61mksYODIWwohS6FcMtHBW5NGp2VMCPSwRWFrztr9gfv644LNqcFlt0o9sY/pHv9gaDco8FUWzX'
    b'h3vsFdeHrpbLMqc1thDpZVNgRcDVbCeVQTr3FCBoq7WxNKryJmSTwSGAjQie8V67a6yOQtvYzREQ+Pca3ccYXNbiYVZLKY8xCq5L'
    b'pneLrsqfCNg6jMAaQIMSWwCoU5CD63pVoWhdo4ME1y2MUUAoT2Rte2ue8qbWVzkfEKWNmaW4j0kSqIjXUUBuNjjBdlIkGsK1yBAu'
    b'OuIzXUV9Baq4bkn6x2dXR0Ny/MPpkLDMH8gr0pBapjZAkPRvmA8R+ApaEQWC97bYAvc5iGVewysaNyEbkB8+XEGWpnui0xuReE4s'
    b'g5ECptMNkTtOScS9EHL5RlSI+B4uc7z6RF4QSJZhG5swwEpme7lj3qtPYwXtHV4xzWK4By+J5/lree9UJ2xSeUwJRMGS//Uf/5NE'
    b'8DoTiRMWyavocJ1C6LFqhRBg6pGOzo4JXHVIZa8lnRECJx+hTBZWoVxDrI5hUu7MViBzidArmirugyTL9xT3Ppd+CWEgC/Yg/zB0'
    b'zcqE5MHmOi6grEG7ptAaeVWsmZtGKbSgzv5ScASyQitW7Rz09Dga+AEbt6FoVv9V8VrdZpBnBV+0aUMqf9JH1u8N8wIE0orc9tjt'
    b'klN4HYkmsFHH4lCu0/+2v/fDc4KG2TlstDrZgxaHMiVLCim2FJQ0Yf5aauDkhsPjScsXCYuizSjNIEOBIVMxHROmfkDyyO4Lhcwg'
    b'1/cTsr/H/oD1CgB5CjdLM+lX1w4onIYH9B+kX+bjao0SFxkVykLCQKiiJlVFyW9KA/2Na0Cqn1oFwTRc6P2s1gZUUQaczave97x3'
    b'10jdKNTRxK1TOGEUgfD/qIvUchmB/+HQxv7RjlCtOWgLdBxxC/9wmfEeiaKJFmTnloHriFyPR+l6Puc+Bz1RNsB7KZWOSraoMpxa'
    b'dckEWh1nC1SrgQnJRcgWWKUmFrQ6CraBdLQz4eZT3wIH60F8rZ6x2rspOVcZ168fyV/bs5L7Ko3MJlZ7mQbFu8S2cqUGv1au1eh0'
    b'bFHGHrJDwEklbnBftel0lwdv75Tv8NXckbtlLNG3P9rnQm+D0tinNcEirEkweV9RWsD7/8yhq9t6stYtvLInq+QVzHK87ScBfW9e'
    b'7kNOUikYZe4oM6Czhuca7nFhLYxkx2tEyMU5Qg1cbGrAY5mDVkJRN6Dq8E0z0b/FvP5Z/26AysHtkNwBhgYqY56xVdofFKOzEhDg'
    b'Kuh9URzzFbKpCGbdEFZTBpmNMiaQ2pMv8N+vQ03XyRf1i3WJX4LWbgh1aP5+8mWri1MOiPhIwuSLSY6vjuv+QUH8j/pCmVp28nFW'
    b'VpuZccsl969cYCrFGLJOfuYqTkCVFJeSx4YVtdtZzxP03j6vIe5owV1HARNtvoCSeltpXj3tuaw45UG1mBOKwW1h/ilhWieB0K6V'
    b'UDh6yrASl+mC/MaaljFPedS/7q0jyKe4iNC2WyHFx3zCK32UTaaFVmFVG9ZOt9oYDW2vWENlBrquBbLFLGJsKSy3R8Summ2L380b'
    b'ARZx2ScHQnnV3zzBrvNotGyKl5BqU75/NawMJbuMU7P+3Q0ji4EKMVpRunJsm1phJYOHBQO5YiucW7AF+U3RbSEl2nqWNbF/aeXG'
    b't527oVBigW9GwD5sdcPBmvBvxsA6SjWecqyuWrvocvIpq8t63y6yp/y6O3iv15uqPqWN9IH6GQ4SEmmCWbou3TaNAvL++IrQdcCz'
    b'dAxPxecqQav2sZ1GYIqETouxbV3XXCbI4RZpt/P0jWVnO47faKLzc+esWb4rVYxNV8VKFUudNUAXVMc9Lae3El85cPdhqZsVfQkb'
    b'ymzUmPQzd652tVfWWgVRpjqR1QNVs2xjaBOsxtVXRzQ7TPO1FXVTCVoxaPYnZy9mxktJqIIHJbHgBZIUMn7L/l47g2V0WlowQ5oj'
    b'/w3p/zPndsvxjPyqm0n1qeRyljIrz4rdTTzZtNKNe9sDruyGsEzKIk5nKHp1U01t2imTPAixanp/Z14fQaNb8FKwkC+49A38mnaG'
    b'ukxAdvISC6dQuhgL10xF8MEpvUZ3bUiYA+i0PTMAMRSmAP5Wcejuvf35AgsPa+/osANabWuo+yT7hc5++wdydFCw7f7vBofkfski'
    b'2DlTno5w24Qktog3OOFWLCU4X0x7bM0zE+lHsczggyneGPSqYA3I6YfLK3IDO7IfriHFMuS4V0CMLblwAAsGaYhDlqbgkoVst6EM'
    b'V4EnSzjmAIUdXgXBK0iIMnqKIX8cvJxGeku+WI6w5ehmnY2ieCRx6qkB9dl4MSZHP/8Vcy0qQILdkdHrf8NtMYpJcWmAqMTH8jkU'
    b'Bs9PgcsEUMmHMW7ldjene8kfvIKehlWu9sBnGqJAkzRmwxK3DsiuMB8pGh2VIU6sebHrz9KIpax7Ti62LH2Rs13Ion4wIKMS1Hx5'
    b'V5pZZkIUsIbZzRqibYOzDVWGPU5Swol/h62owUCorXt5z4WZT83tvwjzx5gOuo+l2WSpUFPTK1+rlmZKe15Ng2V5zh12RpwCkBTp'
    b'5IvJBF91AvB08sUmsjJDwk9t6qwshhO2jJWyEp1stfPyCOWel9KMhSGHjNIgkPUasitZCdDqGnTevUv5CZvTis0hzKyU0FCmTVfh'
    b'iGM/5Ek/jO+ZmKDevE4SJib7RjgB5C9Ux8L2zuz6RV/7HfpSiEJO1BBt+N0GpupXw8pdEe6tWdha4+zbRlETod7YcaGfdAibd2Go'
    b'rKktqKm4inx2/nfK7QDPZ/BsrR5bx9ybKpng03eEr7Y1dvH6m7poYNx/wR3tbyNP5UVJuHIYwHtYW9Co+5U3FdRqsDwyrQ58KQ79'
    b'OcAogZygoD/3a1aSMjYkm74Z2DokmD6FPGtcJgN3Y2Nstrm9GGdRe9httULCcCq8+1aRxaKUrWAn1U/EYUOQFHk2g7yKBoo1ldrm'
    b'0+wRvfg0wwcN3f0gTLMTUBIe0Qs0Q7+Xow8J0uxEpwtCtQFYRQXKFtyRE/VZCyISTk5Kyx70XJGsGwyfZlUAihzdIOREsICM2vKJ'
    b'Gg+Jmm1LpCoeAqwQC6h9n1fAexN52TPS3x/vkee40MmzslpSoPkM1tXL11jzu9fkWeOSNps1j87Cqrr3lwYp96baIdpb12PG+Oit'
    b'0YWt6idHVyJZUo8q6BRfVBUb6IKKpJ4CUGpP2Wtj4E8zZYhBzdjVwKOM+zyB56E32wh6+2TVgGyN6Lc3wL3x714/bhswDMm/woZQ'
    b'8IdJJumMLgdW5dLSUVfLTHu+v5Pz/aqY75rZMNt1vbjXog85cDT5pHqfSE3RE2SK+NarV+Wp0aYyb8UfwHdYPzHlmo5peSLy5j3R'
    b'kC+i4kXjBvJ+B2zQomfGK8iYmBljLpjk16Gu7cSXLtY6+jrq/moUdvXVSuF2BsY3w/F91sKE82sybyltA+hQHckr9a3Hk1e9BfK5'
    b'9WIoxn+bPQumtStreLUi4/E9JV37edk+s9sxzLdPrHxTxnhFXZuhnMpAuboxobZ9x9xBLBRbRq/gS/tjbTqA520KrvUmfBlC8dsL'
    b'cjDec5FFhQxvihQ/texererg9hZdvgqiTRGUNojGuaraRVoR6WZKMU87uqfcMNKlj0Yrimu0FdOCqXHVzsx9c7vBr63VNvZeN2bT'
    b'rgcueyYwzLpfZ7IgI2lQIS8gx8VrS1Uc7Y9fF7ri64pMd1sTZZw9FLhFQA0ez5yot8mfFU9TfKPdNF2qk2m199Y25twkkhSQ5RFe'
    b'42yYUpyEoXx1zolkg76PWDZVqCe6oRPhLaGGCvkd3GUsstHFJUlZQoU0z6IGEEHqZfsWrmD4JKG+uwfXX0U2yphYkYtLuUXsEqQb'
    b'/8zyy6RjMsWXF6OAweNgLMrCDThmQeOAjrOYLADa/urFyxW5Z/Q2YuomxS5hD0nIfZ6pB1iJoPB4KjhqI0LvmKDw/jfhGdyLky/e'
    b'fbd6sX+wUs5WdYFVpB7iikYhVzTLvZdXKVbRSx2ykpdhyrMgvo+6ACoqm4aRPA5G12t/q6WKmeL8alfdgbmxK5/+8uqoHhYsUlpJ'
    b'Bn2f5X8YxiMnAZ85PjssszZCDqOC0xBn7Cg11idXDdN04yq3jCWuCobhw9nedZh2Vqwe7VzVnGeU9opK23ZVdKkprnot+6cbh/bd'
    b'wdWungcNDusm/p2KmaXy1KpDRQBBk6O1ypQ14M3Pz7spz6UdJD8xldaGXQ1foFMhRqUBdu3K1Ql5jkmeq2MxKJR/lknxi8WsNx18'
    b'Mx26JshNIOjlbWY1X+UcEBDURqZvr2YXcmcjXO8S4JNnAUljQgnMfshGqzjKlnCjj97AIyf4Gh4JYv/WTIGg4NxsyDqB1xYltIO9'
    b'fyN9DGeC0DL2AOFrMgJYBv2uBQ1H6oqIbaiT5kVkVvbQtNvkdSQBLBl8sKd2iAKQJkibdC+DdZjlpQqT86nLAuhYJRYP9D5qa/XI'
    b'GuyzKsa5KN83Z392ZCTNUEkr8rnGGEj51NoInlojN3G0TmXQ1P7Lt+Q5eRuLFXmlE2L8EGdLvdsTKiCYKoFr8ZAQAy7W64v0csHi'
    b'jMunke/TP6p3/CD1qoJmPQIPdciS3jHymYl4BENhAdGPNELMWsjoLV2wwZj8RT4Qr9/iVeCyGPSIPalK72EyjnnIE0l2yCcCIWZM'
    b'YGoQqQynzC+ds6yr6rvkhV0RTz45NekcYkPnXKQZ8UWMD+ESfMgUI+OADvA8qKSdPNDV82gtJto4UUABLNoAWZiWQLBsXtucZXM0'
    b'TPFokbrbA5Z5gPc251ENrapaIUhY3I+FWGjaTuBIjG4oy4jkRlQRWidsO+FXSPYKC5hbSSFFFCc9M2dC/QH9tDkbqjalMgY4wIa+'
    b'kf+elQhb/P04JIDxOk6RyaIVckJpt8nJ5i4Gck6N1WUdZWBZPTPGIX9//JQwH9SG1SsjL1T/kTSv7WD/5bwEfjuOcgKuTpCXLmkQ'
    b'38tOtqSQswudSMadPquYFbQePHvMma9kiKlOmlScwWjTpQOpTj8KfrvDRt6aceUZb+M83cl+eyfL77yGAKTHsjhkhsiWbMUU0HTJ'
    b'k5qZRNNeSwZIhJRA1PyjyPCyvQseBesUyJ3fKZDq0K8wren6xiu6s2Vdaz81y8YXsSfYAp7lhjxALkq3WEXlylMwvh2lXATP14bJ'
    b'vzz3BwfkmVMo2jQ1ahmSzeb038s6DUKqOk/NEseG/zLHoYm3rTZ7IEIapqdt3y7T0Nyh9tQRw33bptxS3mXKYnmU1bMrL6gYlxAE'
    b'vffkSaF8aa5Gq3ROsgwetl1Dzxp4osEtBj+IEOQWU2lPcaE7sz2XwOcN8xNhGWjIVxx09373R+xMFMf0Ju0PyLMCxaKDTpNYui6o'
    b'qT/Gh3+LyfjeRHdo/mETudzuT2RkNRzVt3QRvjqY8gn2eYdhOt8ZVze6jNj+Lm9gD3OzCBiW7IB8HY4vg44OzV4bbxHg8OaFaxZY'
    b'Kf+jYoWZmAhU6zntWSp1olzsOe1clwwhOSpYA7OicXGz7QmfCG+9Iq06VR7TmkPlHOIyF4KxwDKQ2dcV8g5LIP80Ma8MFfa0AqZt'
    b'89PiroLqfCENNPG8/WhgQNdttrspoPuKtu8q2qon3SbjYdYh0N8XkEEQtiZ5wMxjJmrDy0sBC40A5PaVshVPPX/jh8zj4EWUsZFb'
    b'Qap/o+dRseb5JD4FmVzxqVtRKabq5W1345GKZ2kEAqtkyQCQsjc+ii675CiGW+WC04iwh0ywFRsBR8qt45DM6R2m4Q2YwJCOgKis'
    b'mRmYZ9G+i6ZbbMNTDUMB7/3ACLL2RtaKwZsozYbQYL4Oe2iku1lvcqg0I5QEHLwrkbTrzdW5aZulpJfQa1xDatjyjxULOI2UgPPz'
    b'4XsKdZQspgLRP3iNtleNBnjq4dMAhFWO25/Iwevc8l4GfbPePAnnwRRIxbO6KuRsLhlNtuREzc4ukLvkz2paoGp3wM0XnSTkC/we'
    b'ShNpd9ANkXMS7lH+2X4oc9Qs+9hNBmovZEfD1QSgTiALNmRzpgv2iNXVvlmV9joz1srYQp7ZUv65tZU9s4WbcazYH6MUqeHwZy4G'
    b'dXnsKj6tbrcrjEbq5tDzNoJUfSAdutoOekm9vBegOdkhG3K6PcHgCq6cj4Rmy/SQBNzPICvnkLyn2VLxgdLI3HdM4eFxyLwXMrjC'
    b'jtkcZO4hR4cS0NhP73rqzij0cpgjQCYK3RRyWVQQRRwruRABZG9YIDkkZj72o/OfZxfTdzPv6Pzkw+nZ5cBAWnWJYK97Mhz3RWlA'
    b'ErdgDPfEPD+9QyQwgB7+KODonC3G0zNqIoo61ozA0hZsqZI4NM1PzdTUTUuJruhympBryRygrMGN9rytokcsiA83to/OT99fzH6c'
    b'nV0e/2wnti8TslBY+Vy2zWG6M1zmz6XXc7wxh37+bKgFJIojL1qHcNKBu+el10KM2/zu9zOM5oYKHd+nY5pAKJF9BrXvvMNPT46s'
    b'd0j8auxsT0OXl8J7h3l3TXUx9KB3qE4VOYIvSIS7b5TvuDaQ4nq7HC9EK00sPujDuAbjFIy+qNik/etyt8N8RB+HhKY+i8BWNLlW'
    b'yfcgAcnHwRiu6cLzBQF76AciTiaYmMRctaUlVFr9JqO7ZIEegF5VzevJWEmCJZQLfWKUrteNF7AkW3rg3vUCThdRnGbcTx+1jNwH'
    b'SJPRu58j/bUQEAFnWjoqphYgXD6QT2sqIEW7R+8oD0GRcBlhzHXY2t7K9mEtFOOSklx47Q+pDMxxAY9xzFCjxvm9WmKgQsp4V7Ni'
    b'KS8M6osD9eT1wWsHCSX1OV2UxLYUkmmV7/4e80izhsEHBcfB6oqzAuaYPfAUcknUTGAmzJRDnKqHHfKdIQeknHQPPuQWnuE/PI5q'
    b'oALfcLqQrAMO/PY51PmJoFlF1NoEU0m/rv1CxF/35HMeuPj57T68T9UT7IaGFExW4NeHL62cmMt9E488qgk2Gcy0BceGmqErGsI/'
    b'mG43z7SruVkhWpeMKR+JssTpv6w0IfDaBxoUYH/IBPyfJzV9OAmK6Fk9WR+26kzSu348shzVwlisMOrV8/mt2ir7RY1yijhXDw2j'
    b'aevHrJR3BfCM3mSldjapZOHr1q5G0Jk80xWD78lembWKJVe3coCYpVXRRtVS9WLo8CcYM/vuejVDrcPAyTkd+u7UMcLEJ+y9W7ZJ'
    b'HyE7DMGgMcXUVc2youiyJDG2wGX7nkGSFh3UsYJUMxTXjUED8oK1DC5kqYH5EMXtpBfSVGfLxWxIbAMIuPrhcyydTCpUtPVWOMfy'
    b'SGX9MxrW55OHBOYbKRfhF+dTmgUQOUI3JFmmwRl/VWCicX2M4+zLekMSRxOTQMv4ftIL2RxObPj+xQNLJ/iyUw836Z5S37358hNt'
    b'eGqny7LfWh/qpAe1Ps9T4I8j+pZBSJJ0Goms+msNpxO9J3LU4/slE6wf0tVNQEl6SMBntzc0SGJyC6ymvkJ40pUghdziiwjNYi7L'
    b'R7G1KS3Q1A7TiCbpMlbWD3QfwcmA/MORL+vRtpFnKg0X5CG0/WEyutSVd0s6wVJI1IjeL7mQ8ppw9FIVA/spH3wQoFSv5hDjz4Et'
    b'4bQ1X4ADa/CNRxtouf1ZbEiCHH49iYrlAmeLmmpF7s0cYg0dLXA2zkVdg6ypdPDZCJuJONEMOKcYCFGTAVS//NWUWPRaV0KlDFfq'
    b'TrWgcl7UZQ0qRPk9sk4YGH/pk1q17xJgBxJVchX2/RpiudnamrYu72IYQJ0GUTlt/2qraH2vTaZRPw5R+cmJ0GMJvlpk5GRPK1/m'
    b'/nxT+aauaCQQeoMBXUVZwhbVj4yKCKOHVGKLSgVMbbpmteUL9EisqFjwyHxtoxcnDGxQ0cJVWDyXqQFv4o3duqXcnzeU+HQhvJfu'
    b'z6+tz5J3wC8hvSbqSb+iAr3zyiMpFZdBWORNUg+Y6JMXsYfMVTLf7Ls/H5Q/59du0O9amiNZUvC4tP5ZVTS9qO+zEF9RLIrlwJQ7'
    b'2C4CwkU8d7HZhXaoN7i0YDuX5tHWami0tLBYw2U5qSI0gMJg4ewhautHXsiSDpYqgNrSMgR1ha8ZUEOl5tvsdYjVVIrvIxWDh9US'
    b'HoY0D2I1KdmcB6+hpuuCeN141KgLJdExnKY6KfMhxLHCCOp7wMKMOksxfvLlq9ceCJJ0SQVL62qAX9BcDh+7e03yJ0fzdaUk9Zet'
    b'1t6T0Uz6BPIDMiDzn+Ol0X25CWR36PDqaLeO4WyGI0TFv+P28TgA/l83UZubKNd2OvlDH+OrmTOKN4bhXFCjA4ECvk77dk0AcYjK'
    b'UF2UX6GdTaPNR8kMEpS9FLNshXEpvUPbnWbEnDiL49veoXlCw4/6KYT4PoUG5gJUdqXqMOodDBLdHUvbq9rVnpOji+Or46PpiXd1'
    b'dVrxyJrlP09PPkyvjs/PKrUcroy54chIqPi0ZpljEob6nuIk5GnWB6qP4WAHhh04wac6pLje8WF1u0XXhku3FnaVmmougjlEbUHi'
    b'DPCuBHPD01K2rurzmUM2OiYqmHcyuzpq1ZzWtGCFJepqBhkD1ZFc3T3Fem48irN8po3fQI0kUN7yvHQg7USVI786kbjP/SYdYF35'
    b'8Z11QpEePwni2v+Ye+i1n8/ejWyLlRneWgQmNHG+sXGb58t/FUoti00ipqVPHkAsN07sXVFQIqHJaXVsiygXDGvgEpJNCwuenL/r'
    b'QiYC5+o/rBol4Qj17E9WbVMsfjReUJDf9TV0VTm+xTp4ZaOQEZpO38vUofDIEHzTUkHvFmjZL5HFaFKUlBtiT9YupZkZ9ykZegRW'
    b'BBQ9NWED5SCbYrtLr3v+kvm3Scwj7ZYuYKbjv6dx1NOmCBre5kdyES8ES9On69UFvb774qViSB73WCQs2a0GLyHGcao7GStJr/EI'
    b'YxqokC9pvWno2LXZg4fbOW25LEscW29lM1IjAQqNAaW0n8iNCV6KsOKKumxC6kXg4i/FXhTuHOXI1kalYBX5NpLiT/UHRDjSQ3KO'
    b'PdPw2iYIrCfMEQW0gl+MqBUnlbV9Hwug9Rfg1mwNWo38BULV+YqlGV0lvUOiN7ZxFN/DsxtpDCcpmvWxUsL8CRyv4ihIIcK0h+j2'
    b'DiXasOl++SoJ456wsbTOIcVxIoL1KkFzHqiYUTY5GOiHeCUADoaPdQqnoL6ygNsUsUk559GCCYwBNmiYZsIiHEgkzd0+CltYufCW'
    b'G8Iaki9fTUnmxfC2BLyJIpgvn3xTNBySXm8wGOPdBth/I/KlB5bQkMG7lOg7hbcAe5bimAOt7LrFEzcQVFMMRSs4lQbll8IsHOXU'
    b'4GDkBwOiwhzUCGhjlGjyIzu5RMxjVm+LINxuHSd0A8iRSYelbEkw2QwSzqRwJgd1qq++DhF1pSoZj31/syhwUrDV9pzzEKp76SE5'
    b'hjsoNyFDVpZ1ugkKZWwuuKegnnF0KvUHsiEWGQv6Ka4J0X+QT4g/SLuDVdl8XqC3TuBb4NFsW1FiGDurIsU8frXxUo2IySfaEjSQ'
    b'u0e9pHdwiH4z+ca4fNgLbnlcfDi7Oj6djTA1TJ/i02oEMo+lmWB0hdSggqdxtLNLFoIHKaCcxGk2kg+JYYx/ClmNVCYZ+QAmPlJ2'
    b'dn4FGYdUji9GOABBmeEZS3JMzuHWyT1PGfhGIBkNjTYkYvckXftLiTLhUZG2xaf+ku3sEgj83xAgNzoK4U75K5kICjPasJs1h8H2'
    b'//lyb/TdHrzmPiBxpJr9+cPx0U+QD2a4swtZahgawc1kSFjDu5hdHp1fzEjAwGo53tnd2SUX65Ad6quCBBzGZHr2i8L0fhmnjPhL'
    b'Gi0gwxJLkQ6KtJaGsbOrHEsyzWAsyOkJyQTl4LQgPErWWTpWL8xl8WIRMjV/Q2NeRjArO7tSyg/JnKYZ0mBI6I33ac39W/yT0DCU'
    b'V3jmm/GOdzH7cDnz3h6fvZtdvL84PrvyZn89OvnwZnZIUoYLDXdTZMmeBUhZ63p5R/qDWIOmrtHyIE0jaM2pWW48moVBW3l1s1Jx'
    b'GsTLaXcqCrdaUXcBedyC+L6mlnqnSt3ZbqwDzsAE0mNt6uplNApoGEdMN8lxcDewngVtqUu5N4/XoniQ0U0cHMaKJt6KZcs4cNXT'
    b'Q40CDpwFT89BNCm4w+B3SAWmp0W/YLj/Wq7q0xNjScPTXynpG/IgnsvVF6h3BCFXM8f7Omqb6+Ey3H/t0X0PY4102kt9kkmLJyLt'
    b'Buk+1Xn5ErGOWLkeLAxY2LB2kpZC43HvxM/clUoZpuuqqXvG+U0mo2JuHcd8jR574FkZr1IVeCiZ+WukhzUN5YrynozxZKyqlTb1'
    b'pQthshP4JfEzntvXi3KclywuivWeXpHNfcfF7dSPE6mQ4t6bZioswZ8vPAxCmRCawi9FbAY87yp4AtIWpLXcbdRWBEnqUOq/QJGp'
    b'ZPBKSk5p0tKSX8FSDGiJUvICZKfBjeMyTl9uD8md9b6fLtSP72FEmbai1UvIr/WKBkNCeXdMwFT2Dsns7N3x2UzB+nl2cXl8fmZ6'
    b'coCUeFQRffzdVBTQVbWAyxoKT1NNEBSS6bkUALwxAVZNvOcw1AnYJnmcm1LkljRdhvxmnC7pPiQaGLPIjwPW762z+ej3oPcv2UPA'
    b'FyzN+lpr1hMh3WgYfOOwaBfa2BqC4GQOb+Z76xScPwuIrgfzZS8/WWj9uMceKChfYz9eYaDHGhWk3gakIltRLt/7XFMzzQWoDT+D'
    b'E20GRsl+73J25H24nF1403ezsyuyWqdZvlNTIhgFnSXK4DVzBElu2BwYiD3gwoyjcRF9os0xsG158o3T7/EjCIaoCYtSKx9fr0V9'
    b'mwUEWzu60de7jYZ/Ivtt3Tha4aBv8EXs/W79bDEsR+v24eFVZP2w1Io+eJDoD9joTq5X8idntSZcWkEaVCjXbcMuisFqh6kNgAMb'
    b'6miPMgtKiRA6IKx68WliTBnZ64ac2XFTvUdgZIBuoKGq/DQTXen515r5SkcG/sDD4K+FmQQkZQqAgPl042EmSeW6hnLI79CEY21b'
    b'jdsNy+4Zi8genpfyZZpRsWAyVSquSPnnTQihK/sr9SCA9fWl8+t38klosMhriG38Oc0gf2eaEXA2yVYEgelk4xp17RjXOCtNykDd'
    b'Tipvl6uxHEgE4ed5ba2DV11qvVSDzSeyjNBWI5eNtyKA4n3V3/7BygvoJtVspD5/J7824VEGoPtbCEYznebdBudG4eCVEwUNuAMO'
    b'OYQmHDQ8NxIvv3MioSF3QCKH0ISEhldCQuk9xaFrw6ho3VBrWtVsqKC32Zl0VGYWwVJ/bRwO5Tk597uD/gsalrpgpXXOL1Y53mIL'
    b'Qx0QR3rxfN772oR8Q+f5CNCRPD8kRk/wrK3uZ0ji+bwkEoGa9UdtSaEmtNraStygJ3jVHhy2BgLwtjocRB7gYs2+YabrgNTgm7CS'
    b't46dU6+eXFIy2v3Ap5JXjlc5yyXGW5p61LqDrQSXPJFrsB1kVnm/q3VWdtjvatu27Hc1aNQ7QLsi0wChHSVEA3MlrQ4gPwqDdJXg'
    b'7JGHdvKn5mlpamrwU1nTU9mZIPTxsX3WNW7oFSNSExoxyASDNwr0zZU2YdnQsuEEgq2QVSBCzuyscXx1zdpGpm2Jj+itpmlbj4ik'
    b'fqgGVE7w9MmNsAM961s30FRuhZChTM4DtPP5bWuPte1q+iov1XJ7DNv147vCctVluXaA0m3JlgGlGQ27kb6hZQPZcc+INnB/Bm4J'
    b'PEC0PAagtvRW265rX1B/gzs8ZBhq4eWGlg2sHCcZX/HPqE/IRLIQRJ3xO0g21dJjY9uGPvVbvdv2V9uupi83G3tgv0hTI69hN8Yt'
    b'tdt+w7OPK1tj0dS827oB95dMcFKkTIbbEotsCaTXJhB1xUIwmc3arNKEn4ZJdINGEXrDIn8Jl7O85XoB5uD8tY+WbuobNvSGV5ok'
    b'+9CQQYLxjoOqb9jQW927s22d1bZr3Irq3mBt3/tqW3buz3yUdLv+rJYd168xGZhrbavdp77x9ivZgKUWy2NRqTTvtpLN8IEipA5g'
    b'ik3brtTYtmFnMtvB9kJ55M0F+7Rmkb8ptNfOfdfCaNodqcrMo+IpO6nM7kYNPA4NlG8xi5MEZIwAt2CnntwNm1ZU7EMglcpA2FUw'
    b'1bRq7UdlQ/dFfB9sIXWbG7f2WgQErDOZgfImjtN2kdHYuLVXZQPOc3178MqiudPVVDNN7h3wM9uXrPy1mGlv+SqG+yXrlccwAQUc'
    b'Q7aakS6AGrApSGvdmNtqkjrB2B6Hws7/TWhUwHTCJIWclRacLXGoA9Cp9xUP4HXRx06Du3n3cev2jxmy3bZTn/h45COH6mjbqU/r'
    b'RcpH9t0AoxMORQJdKXm6aVGt7bvPszWAx0y2A0Cn3rM42Xeuby2XraoH3yAKsjghhsMQWzeL58YU+a0yubl105EhoAnK8cLKHMe3'
    b'0jiUa1aaPNXKYAntpoFV2hLd0YsV5H9qVcEaO/++22C2QtCEb0cgtPbToMJX2xaaV7sG39B6+9NEFdg8jOPcwfAodCwI3c4UVSAZ'
    b'W2HWCPCTtrkomlu7wx7aCYE+E+5/EylKMB5LDMEgwtNb0nDuhXyuA/seQZg6SN2I5NN0mZv+waiYoP1NGbG7kKgFwvYMjACVXUod'
    b'aOHxH6AMPOLTiku1qRsHgNYRDTWY4FGIWI2/GZUVD9WTIgUurzvjYreuReZ15QjrpKuUz3VjfcRE2QK5DnADchatq+hZw3/U/NVj'
    b'aMFumsxSaHAeEp4Whr0Oq64dyqNNytqG9yjEWmE8EVqwjX8jVgaIp0KKPnwzUgWIbntL29DkKmjp61toZy+Jlo4aKGrG3z+O91og'
    b'bD/JDoDb8V0zgKdBaCueawbQjeOaByX5rbGfx1PM5rXGTvI4w1gQCDjG/Ll5x1Y/OpGboeWWEsK5qwJi+pXQLtXBZ8vT27rKPo0C'
    b'GSlvgIdETlY6O2t9SZ+aClTFlw7ragaCz7NONZdgTndXNLFt6tqs19SxWa+hWzW3EtKS0UDE8cq4U1OBlYh4FeMJnwULZIr2msZb'
    b'3p3q4+yUc4Gp+dapQA2YynzqYK/6NtDFPBYeRtpJIuiMXcUSwogz9xN9wPbGxd+SPJENKzLDuSznvS8A7Ouj9qQypzi3pNL0d9+Q'
    b'KtCb9qNSL41olxn3adGuQH882k2r0iGOt0C5EXK9LO6Obg2NnwDdFvp2Q9eOSG/Xud1h57W6cKl6s/qClfG1kP1xk4nAWshdzgnP'
    b'3TqbXaWjavUnQG4s3xpBfN0mW7QzqzuzaPstDKJVo61ZeVurttFWhbY22mvdnSaQKVTxh35YtwVPvGlpi/zHIY39vdC+t62GAPFw'
    b'am/p6ARsbNsQVWEoqAHHd4BzQmzgvqZMW20pqY3h9K0wOgYoaTj2057dpqO58bbEgOekYEc3Xr8dH3QkQqltZwuSCxE1p4tcydxm'
    b'OqqNO4aXeDUPR7bNQX3DhgVwj268dtBYqxFOYx7Y9g6amzd5b0xHmCJ6x5Cv+pYN/clr4yuephCFYZK8o9xoB9AawvANvbcD6CQu'
    b'zYaP9OHWg2iiPuZ5WJgvtXab7PqG3aQTGi+LO44dJEG5Rd3yLw8xEzQALSTNvJskRQcBJPU1t1EMbIKLTXm1tuEjUAK1IfkIpGFp'
    b'3BfTDHLKRAvQ8DhOUNrl8q2jUb1jpeQVt5OV4N+NvsqWpo++8dQCd/AtODXcd4KkUjIZxNiRnEV6qRDbxjDgupbOLmtsPWUluBZo'
    b'vVGkUxNTSW5rYJzgFaEcR3ebOt1O5o7LFzVTYExmuyO9S/tHc2gX4INvxq4br1az+uD9Fm2ba2fZNgCtCFTSBWFuhPZ+3e3aGKPa'
    b'rErMRs7oBODRrNEJ+uDb8WtmDk0sKzMTkteY2GZ/XUPDbYgTC2SUB0gP/3LPplVjJwaNdPqmP5Cj2aFENiD4hiO5ARFJXkJGlpd7'
    b'JIsJe0hCyHRyD1n4SdEDjyMDXkiDgIkxuYoTaMchWRwjK4oJ8dUOImFTsfkjuWGbOApkQrl79ltRPPK2SwIerjGpGo+yGC8Zk4Bj'
    b'cpw5Vxmkxo8mdGmWteKyj4rLS9d+bsHbcmW0tX30omgDPPgmrB6xFKRSiO/BxMEWK6HUrpUgKu9ifvXdiOXz1wLM46SnduyM3jKP'
    b'hiF8kgeUBBIH9b42kLKEzuDR4yiRUN6fJ2Vsh6SEK+bJ0pi20ZyGkAkpUEKtO81L7bamuaUYAXUNtUe+rm1pW40EL+Ey+LZB3DAS'
    b'8hXPMJ0QKeHxwsL7hYF0q/Zo9AsuGfMcb6p/VkU5kbrPitPHUVdi1KlqCtd7O9W0gsY7tcBsb8XtrZba+UWBbkMEsyjGyKijeW19'
    b'UJngPB8yzBZlg7e9X119X1DVOlN21qcrN3raMbWyQHWp/33r4bsDEI0zj0h/b0j2PzrUSxtOHPEMM7DiW1rsHm8vt6qaHWDUbR+O'
    b'qerRQHjrCDd5FZ8LyvM6Dbyb3hBMFngSaomLrAXhnMmatQ5gFmF8Ay8NhcmS2utnVXrorFxZMvmnNZjhdNSs87hnumFreffpXbN1'
    b'tHcMQuHenfh1MLahfvXkFN/8nfky3tW8oewIDnA2guiJhG3bKAabT7xlq0DQe0h5umUzyKoIcf1bNrP08G3bghUvEHRRK1TdrJKb'
    b'JL5VhGpJJK9AbyN3Ki2alNRSchh5TTbN+ErmorQSw7Tlhalp3DEnDOoMpRegZCJTD26rcoF3A/MLGZ3qf4+vs0GSae/th7M309PZ'
    b'2dX0xDs9Pjs+/XDqvT2enby5bNKnrDmc9zp16j43femCydc6r7C6BUqDv69T2E7g7a3Ih3c5MPxF5ns1qFOuD8k5aZpiBG63+mm8'
    b'Fjq6Jq/eaEFAECMNgqh3V1XqbnxysdGqY0vcjomWSQfB2wlUo/ujeAJlXSZgo1m4rl3HFDB2+/Im2ylVYjOEbivTBmLuWm0+n9qG'
    b'3ZMdANGaBcIW+Q9agDXcwDKN1t+I0zagtjDf20Nt0sjsmpYrUHvRO7cw3M3lRlbQZgM6Zr0uyNTVd6PyX0KllCbaUrbUkshtzohr'
    b'LaV2j1xJFAM+CsJIQsAOmtLjNsuiLAaKG3FjW8uiCoRuVKy8yK6SSmXcv+2Qe6yteVM6m5qmgs0hj4hOhfWo7i0YTTEPeG64o5F8'
    b'IkkwljftSIAOELbr/7EzsQ2ox2PUfWq6A2rMMhjB87urmJpXDbskSWto2ZgeJvOX8OhmHkWX+jTEkIHmjDDuZq3xJwEXzM/UvHgZ'
    b'Z2gG6xZ6UtO2tU91cSwytVVZAiayeD63arTjkdcG8VIDqCnFog3ESO7eglzHNPDY2nAHyQCC5izw+qio3kgIOF1EcZpxP+3oFK1r'
    b'2OlOeuEcUbFUDZfni7r5fcFOtTU1t7tvT4wLttDQGQLTYVwBl29+dY216gKiY/qtGlpsl/uqHcg3XKCvTP+3ovaI9Fxl5OIEQt3g'
    b'RR8a8s+YFaZ7htv6xg2IyEc8ZIK1IikuPhRb85QHyF98DOrQfDoEX1DOkbOfUrbU0ULz1z/z6pdYEJAO8p0Q/UgQeU7eH5+cTC88'
    b'fH1Lv0hbeAFMA5d2aF1Or2YnJ8dXM+/87OQX7+1sevWhaGs1la/awo8EOTBftYNweMjl7OGDKI4ncDo9LZpDsR8m15/l86J5pbtX'
    b'3sE42fSsVIhFIeQ6CZhOGF5whtWJ+Tacs70cKwsVN9qNq28T1gK3SNnbJeVRkCSkPoN1wcS/R71y9UuGPtDr31YQ/O1HcPfFgi/g'
    b'2XYCnyBrJD4KFMPzQTKKAJQe7hO6Dng2NjsYmGxqoa/n16dg4AjxY8ZElPb1X/k77brEnOB8IZRfgsSC0uOEarVkD/DuUA7eeMIR'
    b'n9rh0WKiHtspXtTmiwjuoclxAPLwmHr2kI3TJOQZflDv5cTr7LAND3idSL4XBKtsIeJ1gsNLYbXoYernj4p5j9fZNVYGANfFUgEg'
    b'CcWlBkBKR88HMiEC3+5JeAhPT2b2aoXWfEjCCNqzaL2CHCCsj2PCZ05FNtkvnWfVYhAP45RBEsx+GDlq2DiPaZKwKOh/6akR9g4B'
    b'Xci+D8vuEJDopRFPEgbPOIbR9eHB672PXy3eideZfmYY2R5ZDVT+WGRpH7iolfiNYqL0TYtXBF9pUUxjyOgtCPlcmqgmUpioUons'
    b'eBXIdZHwrKZ+wrNS3SIbYk0TI13igibYzkTM0yx73dslJwrZKXSBT7IOSW93l7zlETB/2vuYv6Pg0+hao98zrCHAM0uOHFeqc314'
    b'sLdn1Kwgodlg3huRky9Lnl3/Fr7/9uPXQ/I3+bfij99+/Po3mBP1VbEGfFXrEJ5NLXpy9tIbkTMZYcV9jkn5ceh6jZEVnGaKx2Zs'
    b'cj0HeininEKEGwT9k7f8geEbvCNywVbxHbwZvtGvnpE1+Izlk32YMJSo7JmKgdOxbPkTYwnB59bk7eYRvpYZ36QQIARJnu6o4PAL'
    b'igQNPGWZav8DPKFJQnrDwpTAJq+fR4kTFpFEcJ+lEj4+cqN6IfmTy2M1yWrA5ibS+/eoN/57zKO+RY3BkJTF40DyGLCryV/vj686'
    b'81bCs0a+wvLrw5cVnso7/dX4qdKD5CUYXR37FJRoZZ1ZNI+Fz8jfqA+P/EoTnlb+IJIO/jaOADRjf0PywHuhIr7XjPQhZSRhYnR0'
    b'/BP5G2aS9Ggaz2Vdw8KZEphS3eoS3+YDBRRsSjgmCE5bCLj5A48hYqbXLCWM+kvY3zW/JDxz80o+9Ho+gZBhk09+LoTaO5p0ZplC'
    b'1DVyjlnNJZRybH41Bqr0IBmoQGwkGBj1glp+KijWyk+ncEYNN/hO8UjLnPPzSxQCatanSRJuCFvdULGIITAuiO/zZ/ZgopEZ8LSr'
    b'WlzgHoNXQAzfHCTF91NkH6wcboh2sms+KQbpZpd8ZPXsova3fG+RW2IPdl31xa6W75pYJeGZXWzvkFin+GSqGKqFfnoTXseFUN49'
    b'VIQ9pe9sd/hwPVBePoa4TzgKrGQHYGyoWdWVLWBDcnk0PfPeT6+uZhf6bKZGBa+i1yhOdlfr1YqKjf2MptWLeh7T+mY+k4lYLnkG'
    b'z3rDG5/gwb4bWA99QhWt5X41mmrNRjaEXkoNVYVSW6mK9Z0alZxBxEkNbQyPdPbq3u1Wlax3uw0eUcXmo/XwkqZ60UHbnrfkkiQY'
    b'v6EZfSvoKn813TyhBjSjnqD3ckiO/sDP8mnNsvywWnN+1E/TB/Loo1oh4eQoIQEI2M6t2f+QMjGawjOh8u3T0tuhxvxNcUsbzdS6'
    b'7h2S3uIzT/DNUxB4pkPuxzgFeL37+3sAOF7Edz1zOtcCog97yyxL0sMXL4xqL2AJpC/KNMBplbpNvOj33sT3EcwPaGWXsyPiqk7G'
    b'Yy1xgcZkQqA7b8Gy/lqEQ02Oifp3iGpUvM4m3+0NEIA6+q1groxJROsLPhHbB7hDOEADM/WAqR5Uj6vrnsQFRZLxFxgVxnhlQIO/'
    b'7vn8dn9PV/T5LWSx7H0c0xQeIYBY9oH+HZ6VRQif4ZGc/v5egeLqOu8EYokR5JD0Mp6FrPfx4xifIQ7WoDKDy6lfVL5lLJn05lyk'
    b'mcZ+DO8VGwwkV8zD5C0NU2XXUOy2wofvL8FFQl4GIz5KBEtI/2Dv4LvR3qsRpPsj1pMo+J4wCjrynESxWKFJDd7B2d8jz3d27W8e'
    b'HPbKFb2Uyfdb4jsZsSz29/b2vCULE1wvm7FawlbHN+sQKIvBvfnFhi0XMx49jTOkcYfFKCvO8fLh4OrDdcYyN5BDAQyq0kA/2ass'
    b'UHrlC3pvaLJkgpjBc8LF2b/ASOsnCcqMMU89epPG4Tpj/QHqNKaNDKVPUkQTiFga+a5VHTlrgLZ8WLOnD9ymABvaEA3VzMCKPWSA'
    b'VYvlEvt/AbHNBZHGn7mZ3aipakM1J+lL9cv2SrT+uOY3ZSw6hAMcWqtgqhm836ypmGDsvuOe0y3bKL5QNFcTDN9hCwWwFkbwiDKP'
    b'1sV9H6gypkHQv2WbAgQE5etpr7GwVNluxVY3EApDkz4uD2mZK6k4hVk6ExtzYoEviuEggDGEioV3rK+2V/BRJRmZ4T88jlqay0bq'
    b'3fEJ8Y7OT99Pz355Oz26uvR++HDyk3c6O/1hduGdTt97R9OjH2djEOo5rMJ3I0Fw+bJ58VC2QRdZRaqmK4pvRZgrX82qsgfhG5Qw'
    b'Pp6iAOsPUFuW39L1fM4f9CPbZDIhPWTYokuLcPBzz7Ml+cwTgDX+Hzx5CzAlCQhNyed51fhmRvp8no/hV/QP1NjpQGwq0mIgy1gw'
    b'NBb3e//+7yBpXiiBX/6BRvC0t0V6RfWLmTYPAnR3e3hU0Y2RQWggcX8F7xytk/7+YFBsakBzwDeHUM9BBrxiotDmnk9VwIVJn8o0'
    b'KEPrElee5F8Iyu73niltsjoSRVfUxCg8jZHyB7Xun4qM9STsRD6ULbnqtyUNsaTDurvO1xwqLxKEpR2oT7XbMUaUKj9WdSvO1eXq'
    b'dizLtIagpDMs1+FOsVNn6yRkKLOHpUWtNyflm7F353Uqt7oqvmHsQ85CciXWrKp6600fHtLBM/XEocz09S+WqzJv4wIqtxpJqsP2'
    b'kRXbE3A2cjTuQ52UIX1erMTIyZVRPXY4d6diS4FXW1t3nEqqPbg+5/NbQNsABcNRX3N6tWGiyKZ3Rdnf0IBaOgLK6uYREOfcqa1t'
    b'oLzfyqTGpio/FJ2X95qcq/GALP/6PD8k57hiaXhd2i1grmFfU0zvskioznDTmBhd454JUsLnt4bssLjSaFvhSyVqLWnK5+Tz3L3f'
    b'FvvdfAzW7L4BG3e7uXLkmj+KxGRC8BCP5J6bIi38xi250y4sOaCKnRqOLO4+qG4DM02ONS3SPqr/Zp+G17NV97LnUc04T3kkw1L6'
    b'qkcpX/BEAhXUV+SentS1B514o+YQKA07Q+D5OquN6rJ1QAlNU3Mtq3Z4QD2Ng3XIRiG7Y+DoXsOd7ZSkazGnPqiIcGVe2uzRMI8P'
    b'sqUkhWCrEPw9+ELpCNHe2SX6xdiU3DA/XjFyx1MO/h0e4f39OyaAaKB1J2s4R6UZowHcZL5hsMnerAVcyecR+cv04mxnF4wa0v88'
    b'3rF23cur6dWlKSR4lKFCiuPsyRBESUxllNuTQqM3Z2hz9uJb46N8Z1XWX6csMIp0GiifqwZftamUwRURa/YgICDto8QpFjla8mBI'
    b'jgHkU1Qtu76F8ezhJB1JfX365oJI4wQcp8j/+o//iYKYBQQub0m/mHltcbyhq3AMPpOA3GxgAnZ2jckc4WQSyL6Gt5upuGPQRwrT'
    b'A3NyOTsaWT6VPLoHB3oIEx4LxhcR4Wm6BsZB88XB3ugtoRFEaYYb0ofVsb83+unF/t7ozwPgnWzJNiTdpBmDMHcfqiHz8JC03PrJ'
    b'URiTv/BsCYhmSw5Bf+KOjeJ1NiQ0AOvXzi45+E6OBjg4IhdgCiGaNASsPjKnBF0sBLxSBsf+NCUQDUBYFK8XS2gJSO3skr+Z0fMa'
    b'By++/RtK1ZsQIsSLQET2AL+Pd7zpmwvv6vjop9mFdzm7krqhsWnp87HerRRnebi9wkyqCFA8PANX6QaSceQNSeLsRcsuZ2Hjya8e'
    b'nCW2JLcB7VJ4snWcU5av0ImSj0EXFOcMaYscEg98G+VqxmnBjfuEfIHdORtoayGuMDTKKMhfW+RhHdzCRtFICrcVXEoANI92Np0N'
    b'c42mVkuR5j95bLEVksIYoH0q7TuJbgaBsHkVkJXKSCBNmvJSt/VacxHT3XRgdO7FBeTqJtwg/qoy/CO4BfetdvaGJodVt0+jZU9t'
    b'wM38ke+Z/1neAbAcNrgH5rl/wKz4gib8xcONCF+Yc/fi6PinLzjzXw1fgfnYN5xPHzAxTGXejWqDIdlXQSM0zTwmBPgpJDT002fw'
    b'nhKuQkGjBeubbTuxzOOcEPqncerlnZ4m/Uz/GMzaRecyfwBBzPWVyKRbzMdcIoYds5HbC7XEwedVXreKzSnBhCuWKNBNerWsDxp5'
    b'Sa02QILosU+ierKfk33yJ5OZSgcIyjNPM5i8QmZTZqguljkEjvE8/IA8U/WMfksTYBBf9qq86trYWRdb+nQijM9zmh12mvGKzlkz'
    b'7+DXm/euQSH+aM8r8gxqKJDfPRakWOt/VJFZ2IkkAel/0Qh+HZTMm7+eHHWN3FSp64V6cf6q0vVRNDkkBQHU+LfArsBK7v88msP9'
    b'Tg7XgbwNPKwIGY0xQKSPpsdDyzmKG3yu+MFpJbezYW1QyUAdg+MkfhjjQq5oZ6gmwt9Sv/ZWNL0lE9nkujdPCvdo7hJVatKYfer3'
    b'3v5S3AToBWuV7gH29R6IbtmzCsYv+jb7+gc6fbPYw9BZ7svBXpeAfSxiif2YCZ/1BmNQXCLa38OU8y/39sxhJEzwOABZIYGD2Q3W'
    b'tIQ+DmP/2kBiSHqygbMfUO0jWjgHpd3M7KaGtrAHlipy6Hm0/3GME2sph4bCLnnh05qKDHgC3OASQF/+cwgK3ZA4meXQ5oo6Pgmy'
    b'Km0k8CoF9MCTYMzTiPYDaaVwdq/5rp7RsJoX8PmcTAjqCUGmyEFGSDMn4MGA/BvZP0AQnzweQFz2KzTeG/DgGi/KEwBjFLx4QV5a'
    b'xJYQ+Fz/EpEv+0NyMCQvh+TVVwnDmBBrM9Hzgp56aZWcJ3JK5B8YgQJ/50ZD+PxMWdmLGbSKLX43JhF3qsL8iB10mHfbXulgABnG'
    b'D3vxPMmPPtoPjvdPEvNYJ0miFDTDh1Eom3/e7x2SfUP7/PNB75AcmB9e9g7JS/PDq94heWV8ePtL6cOP+yUYP/5S/nBQavLL1ZsK'
    b'KvCtjA18KyME3wyc8h0DiAUmcuW4LPO2dhRlD9nHggU8g8Qosp1UhpJ6QsvLB8p/JXp/7l/vj159HPSGRRf58lw5BZDhuDLWcRRn'
    b'sJBNnjO0mAD0Faki2VVMpe13eOUrkFfNzKcCsBwkGGRRmLQKsxo5VlXHNchas7c1clnZRDgI1EZRuuEhW7wyq+6/NgZ3sP+vHFxE'
    b'vhyADOo2tKdCpZW+rs6rG5clJy3W6eNNGLVxsUgKwDrZ5Ni3sXnN1sSq1VnUYR9LcRvTfzn8jPmeZaynPiMjkg7GMh3Uc7Kvhp4I'
    b'JkljG3DWEc/AbwsXsuCREHTxoM+J5EWH5DhjAq4rXIOhxnVFsdfrvccOyIfLN7DlsQziS6WOio4YeIZthAZ39fV+ySKM2QPrYYoZ'
    b'KMOMJyHDjtOxPNC8LRlcV3SjGpCbOFuqWFEeLUb+WggW+Rvs7sPlm1EmaJTKCGwZNoQAP+A5YcUfIGMvdETogoLuLzGn4hauyUHy'
    b'C7iXi0G1kItUBrIjw6Rj8hfAnUp45ngBIJGnriFZwz6f/ZHE2ZKJe7hKCgF20gZ7R3mIF0GwhTQRy+2XJxhwSwK2gPz8aM5NEwqW'
    b'xtwcbfgR5vRGQCAfDOrtXzFBKmT6jSM52p4S1DCN4A4GYX+rom1hLedzLGNaoDCPx4dFhtNfZjvlVIbdIecZdKrhJKeGWw0/SPgT'
    b'cn1b9Ku71E3wm3bQFVFX2hlbgAEAbCPdO5CcsAH2bW4wBdw+XL5RwesKaN5ag5TrhD1kgvolR4dgfiyC3BpiGjZhRRR2TRBi1jKq'
    b'Cf1V5NUHUIjykzYafalW91QmhQmqrw4uEwwW7RWnBMhKqO6dwO/zDf43wf/GYoX/5mjCX8AG8C9m3e19VMYEuU4nLlPSkHzRN/fi'
    b'e5wASVsacgpreULeXr659K6m77zpyfH0cnaJrYteh+T6o52zKE2oLxMX9dbpaEHhBUPSCxiHf/hcpCO4hGpeColST6MoFzh0kYMq'
    b'UDQIbhzzdWt1zm8JH5B3czjFC1tqlKXoIeqDOqXBIjJYsbKZlhCB6k4knIgg46PckqOWs4JfjFmp7w1rbtcdjF0LCuTN7luJ3EXS'
    b'MX4eODrEfNkTVQutoQqKMxCqNBZoLK+B1oS9OYejhwTXC2A4dhLy5h6hTS3xWnuFn11yxZkY7d0YsdEHg0Mzel0y9X+/PD8jse9T'
    b'+fhRuNF3DGvAyrWPYfMBGDh5lJGDvYPX+wcv90n/l19++eX09M2bAexhSyYgdXxEji/P1UXvcR1UW28Z4EUykQiGt5kz6OhsenZ+'
    b'OTs6P3tzOSSJiIO1r6O/XINXVxT7v93/w+/2Rnv7o719srd3iP8b72mMfztAf++r3/3uxXf7e+SGBihpaqDKm5VSPcVccoEn8ymN'
    b'/fRuTI5QwUJ8wamYCXPHrULTtAIuWcHFazApC/Aq+7GATDXhxk0u1FplqDcwilyaLApqgitts6NuPESjw5BEyRgv7THhWjeOLmH7'
    b'1n+6O2QRKOKlKS36deqjlQ6RwSqjxK/dxpkD2HKkZsc41vyDu1tZTB2GJBOFToOWSbJTOsckhTTrFwO/o2FvUDvuXHmPAkuZ17jl'
    b'4TRAg3TOI56hWHusdMGroyrErRZCYRRx/aAucehwwA6bmynd4xC4rKVqrpwc5pPU0mK+gQwCBbdtem3ozBO7RdLeAnQquxF+aW0H'
    b'KpXVDD60tcIDI+RIsFmzgCIrDKoc2gLYNkwfNp15HZ2V5Fbr2As1EuYy3/Zbxi7zx2YU3MOoI7U0QP1U8mSuH7Q0karsoTITwZKq'
    b'b1A4d8yf/MpH6d5XHxZZfliHmxZu8zpctSggQD1IjO3Jly36TTr7x0HlllYO3NHO1uUN4low9f0u8AnJQ2GXiyHKXhNuQPDdp+DW'
    b'vNfHIYfHx3nSMduYfh/zew0NH3XcsciBBnS8CbdeSdpjnTC+z885yppY4OLHyabvOt6A2ghS0TzmDcl8MxgSeG6HBNKYebMpptfG'
    b'Zr6BiQA+kFfohhiYFVF1oc4IN3I6LybNbrhiG1qA8XthDkR+vVb0wNjw0omn2YVg/syT6lpCWVn9LKdookx8lWJLHk2svxxduEY9'
    b'cX61G1cz4swTZaEeKgyHNip4rYYn1aEDCcHrOHSX4IZRU5i78JylZX9izQA+lqZ4cW1MqjKbDz6WJx68rovyEnMqEzaLmLCNW6hl'
    b'HEqCLV9yTQItB2zJJeP+4nq1Dinmf7vZeJ+UyQX1xdzlZHjl8a4iunQXcG9c4L2ItG/eVrVHrn10ZnpxkcuLarCDrK9SEco/viev'
    b'Op6gK/qj2aMUStUeu6mFzv5sXp4Qszub0UpLIyndUhW54ag3yP1DNqKpV0wVmZCbOA6ry6avyA0+UbDP9qGnCTrUgJ79GpePTMTp'
    b'cPQoT8nAoXkDuMJrmrtMMSZq617Ac2R3Yf+FL5v7a/CDlRgWlSiJx0iHkhmTa5HNcb0vjOGYA3wzKjrhcz2079XLAUWR4aGDApNx'
    b'dKWBCmYBTipYejIh+/J7lIwjGlUpmu+cEiNXuTnya4T70VG5epvBHqvL5FMgWWPiaUFuKwQlknBu24qu7Zjl8J5vj2QOx4Gqi57l'
    b'vuW07nQ+JrqPh+pYCMrPTvP5z5Qd6mON7m0eBM1W+ee6dlsdO5RIP5SsVFOn0A4PC+LV9Q7KI54s7qs17LPE058hVLRPur5JWTbJ'
    b'tQp7t7XbXMP/lcqrVQTyDywxxl1oD//yU0v3s8kNJEazzc4JjSCxaiwggm2LPA5D16XRZndN3qDxmKJOFXDjE1HqcvvTvATrvCmp'
    b'L8gWNzOHRQ8qUBnvJ2JtiB+HnXy96u+btyULnNTThO67lZ55LxLKTRSKOI1Sh3a4orUMetLrig2qlm6AoK6n2klL52BKIV9K/Xx9'
    b'ge/lFKP/CkGPKYEIQEZXmKBPeqzSgfVmjqS0SrmmnluBxFv4+A0m2tKvRHCZd0s5J9XZD06IRisBCQDXsiI+uR7PPfUNPi1EnKZe'
    b'IuK5dK3FiccjuCMGf0QsM/6K/TkCoQl7UJ3lWAJHmQdQRML1ERZyuaAItrC/wxVF7zNPvK53iYf1F0/Na8b2hRl957iJmezdq8sN'
    b'17Ii9a23Pit42wiRSc2V0Opm3BgX3Kiul+ej/pLykHyeDxQnayJzlGR2etd8cdSleK3xZNuHqtppBDSgwwojuTQ4QE55tY0Lz92p'
    b'Y6CrL1C1XcVWAtKBNxpvPs8nn+dOB2PF7W7+4KsErlNabasS2rXXp3KRDhb3rXqoddgaoRmw5iyp54rd8smkU+yDImEB3klHwXyX'
    b'uaER6wIPwfxr+L+0pNdHeINXqT89Opq9v5q98SDBxtvzi9PLqv3jKTF7En3I/NlaNzJ/qmO0tw4tSoCcW9lNlVKodMl6zjK2xf/L'
    b'VtuzFZLvU1nlK1vdBfNr4yEkhCaeNpSGPBvq/8/eu243biQJwv/rKXJZ6zbpoihKdbFbbXpOuVzurrN22VPl7p45Wn0YiAApdIEA'
    b'DICSaI189iH2CfdJvhMReb8AoKRyd89unT5tEZkZmRkZGRkZGZccGu1HEXSBsAjC6IMUIXeBrV1DgptX7+bU2CKiU6dA5xzsCRtF'
    b'qp9Bs1huN7M6LfTHhxvjqsi3iWV1Y4PzIR/G+gAbUvwzRb3eJ+Bha8Q1tGcuDsSVemS8FITw4Gq/2CfseI7+ECd7OhZCdss8t+TM'
    b'aAr/GyKTyMgkfvNs7z71ioe/rGbLvDT8t4dJgcrTFpzZUS0AyWjjdmxy7imjrASE2gVGGoLhW1cDCuBn3j/FChvQNS4QAq3fLrrg'
    b'8i1iwVaE3glfu6iE+hBEtUkxXKfqx6TyUDfWtSfUC+GSGKdQAV8NeYcUz4ZgVZ1dli2pIMaJ+R46RbthTPXSZQnKR5L4GPg+j6Aa'
    b'XwAlfjKjobVgZcyfQZwmUyagmbyGhJuFHP8UAh+stsVSvNJAYD+8wsLzoNaxcKWDK+HSsvtZ4lWSq6DRuoTskJdoUihaOra/FSE7'
    b'Xi6da6zMp8IXUXPgk7UFJzyP805uJ/iqdqj2A4Va+0LFM2UQ5N4jQkCPlyCaKmav9osC7NsrssEeIq1q4z7oOdTlfdgDzZMclvzq'
    b'btIhr/18PCJTAWxDDA6uNuV5nKsnthlG0B/r5ajE5bLNZMrKwrdLLsqrxajctmk9GrSeciDw30Cn0E6NbHDPPtDxctnZPk9XrTlw'
    b'ncHag7eYrylDGA3vQDX3ohzZWKMN3b7Fm82H6KNrZfQ5DcUjtgfNYbkSwjqKoWbwWb0qSSOhSjI4PRRtW0oizlXbSVpnl2hsTTnD'
    b'zMmoF4gVGOqJ0TQLSphcJFHbbiKzTLWRwkSgrb98aiTvWpabcwgRr4bcjKs6gwjq9onYpJBp2ykIa905HN1qiH8adFCjglD0KYHQ'
    b'CSQ+69cNb3VQgMnKgV75mDgoWvc6w4c/owQKGtQkePuv6ux0xAXXqI4L8MiHoFi8maeMnPVhCUpDUjqt6gzxfebh/LoF0kQBILrH'
    b'mKueKNtjvY6IA47fZvi3AUjsHNf21qoQMMDltdTuBpGGg+Djico6StJVvM1bAmo8HBpooVH2sCsDtZblXNwsU0xXsjgl/On/j2jk'
    b'PA7Nv9Ddkfp0zMHUvOOGrwgtwwzjris6NMcjgxWkiRuuQHUqqlhM0qQa42mNtxCRuDJ68oggHAmG/lg2lxCgpkuCJYtsfzibP71+'
    b'+c3rd++jN+//9PLd6/dmWBu4bKVFO0tSzIfhZGXjMYqttGx1fOWmZaP+uElPAeFKxlln6jNkDXkxQ+14AxEcx6OfMJzWFKxecefL'
    b'tdCgh8IHeO4XCTweiCwMgMesnL1HZ4s3P+hpmGA4p6qLkzNh1ZKsDHlaumVLqVlVMDzbkpUM2RcnckkhLyAk3BmTi0YbiWWdsrRd'
    b'Rc1uc959U7loN7m+0BqcgQsOcWRIYv1bfB1l+JCGj6FmMss6na2yIonzfFyPxv8zuTl6ejv5nzNoNJriMASGRLQLDs5O3fluW0D3'
    b'Iif725IhEJZBqJQtOPneaJMQQVIgaD1yblkyqwn1Mkw2eoNl6G7i9i2CVt0AoNvDmzhLbrHff4FnpJ92VbpYNpe/gx9v4026uFHo'
    b'v5Wr9DsIdYV14VhV2iokquA2dfzdkpV2v+UEPjJJx3vlTFTGUE0dM58dc+bhQ++3FIQGgghiUJrsPQ6SiSkh1vTJytyoWD+6yj5k'
    b'VZpksUywoigUr7G4O8BgD6gKAwX23K2xFXfWRjQB7Sg8QeAEARcMyuBVmZp4s6n4riYq0QYspeCtYDlBgE5lB4ZaE3qWMxCPY627'
    b'InfpHO7wCHbBRu/T5RaSfo3wRNF+ab1xm7DRKxJKqar64dRUAw8at9yIoZ2w9lTVP5tBoGclW1DJRIwfKovBG5rbW689i0ykAkCz'
    b'Bk72LBEwz/zmIxTNCpck3rYlvhNqWQ5cCqI3ZBHh3XxRlhIjrwPvyyJFzx7ZeBQEsFccgccaLOmsvW5Ht0E4sOHDMK7zBg1w4Y8O'
    b'IKCszL1gcDIYP0/nqVdmmLCe9KqabaapCUK/K4/Xpo/aDe8uDxiPK6Z6dAVRAX1ZgJmOpvDbY4jpBv4KeJT6xifi4w0BG3AbDVof'
    b'DO5vuPmBD+Qph2kKhrbGE/eP2rv0pt5cZBVpcsbJauidLlnpVytxQt2R6VEOnbY0kx2ZmRXRjzyGS3VdbuSPtjQcQPBAlAx6WaJb'
    b'8s1SbPYTttTkLsEReXhrxcqF8AntT5dnqok+cDr+RmdoHEER+fPGljk1oINkzo+LoW4mn/Qz+VvncAoiSr4J8jOIJkAnl0pkFUYe'
    b'zbavF4WTdbZsIvUzK5JtA4IV/9TRE1yOe7qRCOf3P5nVq2P8RVz1gXWXD1VR4ke6WqVLNCXWV7erU4zH09OpQSGqC/EFr1KyQ0qO'
    b'1tNrWw7qsy3NHvnvIpG9cQ1DqC9Bw6dcUoL97pc1UHAWRBoKe4WQJHkALEVzDjSNHF14fy4+FOUVj1JLtlJ2TbXtyWBX5ojzKmmS'
    b'Uw5CqmgSXT1jWoxbAKtk9p6gkMm4BWHKEpjYojz/W7rkdqsIwSJGj9InORVE7VH4IJIEzTsoqpLZ2/gn1ZkiQm8/go4D/UgyH9YP'
    b'cEBfL0S3gT44Uff0sKcoq1r8ynN75btxHm/Ok5jVJywvyw9NlGcf0qgowbB0UxbjWkGespokIaR/UHDE11mzOHKMvW3dvPnUB6Xa'
    b'25EjX4NQrYsGEBYOuVBGSYgC2fTgL6LKKpQPU4RL16ED0TQXpdCho3vV5gP2ZYoyRk55ihPVRl0Q75yHSAC1FN9WlEMtcSC49LiJ'
    b'hwTenLGqKfPcQxhAQMWiV3KVTIrQEVdVHjcAMvKF3DSHpXFc5KsB5W1RXklgMt7HbNsui/JqPJm1v5D9ZvZLOkYwM8nJxm4MNDU6'
    b'TXQ2x0z9+Sej4o3okHw9xufgLtiOx3z4BzowHk8NPML06OE2vcsWECM6j9fkRjZl80DsNvwIb13AMcisvF964xkHC8ypJJdZE17l'
    b'8SkhG6YGS6FwABB+LRCUwEFsOA/xHrFMQjbUGlik5zs1P/glQwe2p5GfJ1JFz+mjLZwN3fP4qDBug5pYbwau1CVGqe7P0EffltPY'
    b'Ilv0M00CznNxi+QHOoxDCJGP0eoguYiXs91oOAFF8gq396ef/Hv0yebTyS1qHSSugAWAgkHv0sr8Kt9XsiIFrUY4k3HPwGD2qncg'
    b'Tx3okBDmWIXCvXbcT23Vj9GNpqrovkdrfXlvX/qW8klc+7f3PO0JIFNcrD0e+OSz1D6bwHyM33NHUHecnAyUd2QS1qiOn9waDWkL'
    b'+2DZe9NrwEQGRwaydR+dIol7svHCIAJJf7OVhKwoAOsLMx/M2yXqcCKkCnZ2XDNYw7022vS+oKSW8/6QHmY8pO6UYAj7Bk0hUvVM'
    b'Nt0Q753aXU8lOoR4g9kWA0zQa6vqcMZkP5ZocUJtFF7rRA29yV6pNvRkBjxzAeTuhoimCldKqFXjZjeIDrifQ3aDVLzY/bb6MAqB'
    b'f3UeNWmaKOrRFnQP1jMajX5YrTDiK2XsAqBaqmiIIgv5zvIdBczNIcrCm79+fYivlMJjFLA4E7FeISRuhFmueV7wCH3jomii8jHD'
    b'Fk4Lko5EVNdHnVsQJixe8nDm1t5VvR5SQh/MDpctR3s3Vkm2sC0m88C/BKodkBZDOtM3urtQRPx33s79K/8RdrF3qz7UpqOFAqoi'
    b'6sNdZmyw4GBBnW9o832Mwujb7uwKxopteL99XWKrBVNYF9Yt/B0CvUno2rwsi6bN2m1agJ94XV7vOFHiApo2qUiV+w7+Ik5YUbJt'
    b'g7Gc+bP1nhOB/5z+it0/sFbH6sSR+gScTh0PRw+8jQMQjLzy/Zu3EXKr6OuX719Hb19+//q9F2tiixyIRJlnIoOjn+YwMMXiRnZm'
    b'41DEg061yPmOs3lwtc5T8IlY5WVZn4Q6dDzQv2Q3vune6o7lD3QGKS0PtxUVhw3ShS6y6Ed5lrdpLa5qtsGlqjj0dY4D4mYjZa0f'
    b'v9pG16Qv/22Xw1EPbAKwpi9IhumOPVcSr94JfFJ02VJ1tBnSEY97aFUMKbk2PapoDk3V6QPk1zXrYNoyCASuC3VhCLOUKEltDR6/'
    b'2yayqab2HwVJDOp1PQZofgE87VEXLK229liiPhbpgOYq45lndUUskxkEudBOXIzAv2DgVxG+8Z7JlEquOlzd4yAYf0r6UIy1AUYd'
    b'5tpBZ0OIV3XXlmgOp6GTNPMJN1UHiLO4abJ1MY7wWn4kXAe6LvC29bpBMfGKjN/rNVi9mawUXgQehGoAUDfd7E87QfoZTkOKfQvi'
    b'cPdNCFlGhf9kY3iX8RAi+qgbxGJN+j8x+pmWYAzh4Op2phWbQWIxpkUnU3+pdxnMJCbnRYQtjyXeibGRNJ5m7iFk+hqrCu2w5cW2'
    b'wJg3XAkC/zBhLRnX2nEyFd1qGitTltikyNhPN7pqecEBqk7EHFLHHUcr9fPJWZ2S7LPmb6UCydw025qi/o+mK/Q5WgTOTo9SGuep'
    b'9aQucQtUQ7jNc/H/Hl/VO3XN6VttXx6HlPapQIApBInYioDbQcEV4R+aA9ixB7Xp0nOox5AJg5Q7rfDNP9QGXCmMSZEStGNOfBVk'
    b'REAcbTiLQMJ+t2BrjxTxFcRLjOu2EzhE/94f9JcLwIXTTGQlhKaPOujhFHe8wxSUHpnqh5xo+T7Gl+uE8gLOT+byueeRdprC0adt'
    b'TnWc6XE7zKNN6I1OA4LLf4JsKAEiD4XOVGQPEoyb7WYT16Dcsg4ovzla09Y9Vmio4bUPO/Fe5rOZ5hMZbXVDDhXIS8XSA49XjQZh'
    b'T6G1ZrI6dQV/Pwq3RfbzFpQ3ApfG/VXBl2nhYNyOF7x3xOKGx0N8WfEWeRM00oH9L+sJryWeD8QIKtwpFqha4bu6Xgsypl9dZG0K'
    b'Ezea75Z5GlV5vHPKuWlDnaR8aNcK62rI2Yq+8CkZjYQWHo6mFP5Dy3qAFM/rCFcEgdYn3K1DFDuWkylqlTV6B98X+D+VckzSqUp2'
    b'ABWQODWsyic9ORvrbULkcFXoquEa+yRO6ifVRdykR8+icrWCOA6yINILNESv8/I8zg/ivLqIMak3/o7wt5yM2yDatwGMYZ/qF3Gd'
    b'XMV1us+Y9mnzmP0ICGFHzw++0VK2/B4sQoH2GNAeA/kuj3leKgvTWK2jK+gDUhsJIBQR34Ykoeg/vdjr7ZCYBAr2aEONZtGayhSo'
    b'wNKWbrIi2izjKoKsWec8qj5bsC9ACvX7Xhix4Opyw5ReVz6wsWwD6dvcbh8F1ZrXSzPOoNT2vPzmnXozqNOft2kDqd/Ot62352W5'
    b'zUF51/IxgLrzeqkrnD6SRsdBDsybqw6n+IN7XjtIsVZhYf6cPDDOtI5nu3iT43i46vg3RRagA0LiEhDjULWNSeCchGBJdGlVvY4m'
    b'k8kJeFcb5y+E9AIPLo7ykJtBuuSm+9rhCmpD/uhrBtDTnn/VrUf0IhTEStdvPNBpc+B2Lo4/l2UIM+7NW0Zhy0wUInZaM1lYMCKw'
    b'Gw1Yc+5xw98KVx5jIYRFtzefiCAFq40ikJffvPM3JMo54TZKngo2RZ2EBQm1tN0qXcCTCptyX8UubnFNhLG4LpF/gPXOZzwzMNia'
    b'+So8nc/m3PLQZc+QsHPAuSZRBXxEguC5OX+M6zjP07wJHRvISHAbXKSs2cR5frDJ4HWzoj5IejT7GX/9mh2yH7/78x/ZIXv35i9v'
    b'2SF7/fbHP7FD9u2r19+xQ5a2y9lkxl5u2/KAtN90WJ7vGKCB1XGxhqdRyioIic5acHO+As/Bkr+yjrHmV+y/P51/PWFxLQ+cfAuv'
    b'E/DGtoHHAwg1ZWbS3P9c86zvHVi1gvLPecotK3XILSvjjPMgyORBnefe1NoAC/OntafvivT/S85CvjIf9yhUpPD/TsK9TkLhLfJg'
    b'p2HH7fnvfCg2LcRqWGfLyLqz2WekY6kVPvC+g00rAbMm3WSgRNvC0A5fvmGiC938Bjn8v7/8/jt+5v10kWEOq1hxYXFtAyOdGXsD'
    b'SZPTquGnDzzeM5oCdshj52zSTVnvDuEqH6/TKSsrPGxYkbZXZf0BjTvBZf/lG8j4VMdNW2+X7bZO2WXWZGhsUCKgJIvXRdm02bI5'
    b'pJSXmAATTEwhqAU8H53vIOQgfCEWQRkyD+us+cDW0MQ84OBdXMuyaHoADFgWaE98xmcuyS2F0S5J9IT6RtktuaP3GC6BBVD/WJBX'
    b'm5GvApY4nOu/efvtD2caifCFk4ShbNIyxKjH1OPuzF86HuLbSN9ecQ5YLnLAlO9w0g2Ysylt4DHI+3z4g/CeuFAu4DDMGXoGycDg'
    b'nS7rQLM8AvqDI/AjCQ3744p2t5HWu38zjVTKbjcvss+l/zed0UAhhIs5dXzl2Oh55RwgB3UQf8iqUa/5npDM9pHHeq/5pA7ou+vf'
    b'6Q5P77K/xUX+TUEJlWEv/ZQuL4oyL9c7PyyLBCyYDoFova03aYEZN97LHfknoe+dPJjkFNwvPeJTIBXQUOlp/50xKL2QZjBgW7zI'
    b'REPSsSNkLcif5NJlFC/bbZyjQe+elvTKE9T2ydDgUvYHcHzyCBh8KqZnhe6KwQUMr5Gz6kTGJlLbGAqPnq6Uk+hvH/JCZEsenbEn'
    b'kEcnOnr6bfTqh+/+/P3b91osC431oMmwiByZ8KQXvoAVA0NVyNAXZvQAHFcQnhw2TSEr1ipsgRZu3AhhACbhIpxAX/fecBmYYVaO'
    b'684xNAag3LOnH/lZ714hM0xGogbi5IxOTuU8PQZDFpgmXQIRg+l8WjfRstwWCqQwQeJCgVlpKkwIN3ERr3Ho8BnMjof1ydMpBTrj'
    b'pbIXEbYuzZM9+hCB+b1diPS/ch71h5Q7s+3RRZLm4N3QORmjjuywKpsMs0suL0BHKcr37bpzjnqVYMdDpkwn111Db4UT1qkNZTsT'
    b'+jbdHodYjNlo1dZD40UZf9MH3AnCeWptcGVdNoNcaqB4RKJfaAk9B0/COJ/i9dp7wICE9PTZ83+oQwaS6sCY/sscNG0dF0285Ile'
    b'vQFy/gEOGj/a/9kOG0nR7TXfPCHOpSpMGZg17wH7fLvrYchaDfuEOS+364uh55jaoGme951oWhW706YcfKzJLiFrYHePWg2zQ874'
    b'9+0RsIYJkbvQShX+31niO0usPfwxzhPAfsRj1saQsD2wMc4My/Enbl2dXI3K4nR1QdPSn+3V86E25NnVRVqD9kjO4Ss2nxqJqJ3z'
    b'UksAqN0JZWCcfRLAfsggBnA4fqxI+wohAeBirbqDa+OgJDHcD9dzKxYu33pPUObRTnfAr+IWDGhNW9PR0VMw6jsdfXb0dPWZ8o5l'
    b'/AMPMUo/RKzQz2DlnPryo2gjP2A7HvYIO3367Dl1+vTZcxMIfhAA8IfR6TO3y2dmh8/M7tTDo6ndq2K00xU4QRYFa4yayxNTT2aa'
    b'diLiQZMDegFp0kkd+CJUQ/Zma+WumkEL5iRv1VyLTSCOIzCpbbtdgeEfHO6GcOZoLsSjCyAHY70CwfAk8N3iqC+EKswfmoX8LszU'
    b'NlDzIVyX5UAxoTBtLpTDQlECRNIWHM2QAO5S1BJZrroz6YQyZns5eGcIFv2G4mRCcYKuoTeSnxcGvELpNml/5Wt9J0fRv7f7J8GD'
    b'DAaEDVQlVakwuRvD2eJgoYiHecXyCWMUKT0piCfUk4YB6FJ+1yNQWekNKYqVJv07KLBrBHxA7X4e4uI92KMLT/M9nLoaf7SvkGMX'
    b'Xu3XxrAdR11f3khYtiBbEvfGcBw0X9S0Gx+6bvG1XtZZr7vh0ZScCGsd3jyD3buA/LkvlNoKbiLINQ9mqP9rTPzKyXneTMCZNCqL'
    b'hRM3xalZZ+sLqqou506l891CYtUpTLIa4r4CCAghcBXXiVXLWXPVF7mtAU7CKyJxxita2VN8e8JdIWp7J3crxSQD3CsRLHsyoCZn'
    b'46aflREBs2njNehqLlMwPolI0x4IiDJFOxaehcHWRclXK/70CqnirWccU0grQJxKC6kfUhG1DfFKqF5O7vS0Sa1HJ2zpecoryiIq'
    b'tnkuVREQyjFZnS6VQyvczCbkA2d6fZGANO+CKi7LaINrwd2kcREADMyj4ODBaPcOL4iGeQ1/3KKVbfBtazW6QYlIrrsKugciCw/R'
    b'1h2ZTYvIRpSkQuCQXpmTUm+Y1KpOL7Ny20RAUTIsqj4nXlF4hzmUh6VXcc0v0LiOkA5LWDxb3YpsDuAuKEMoerA0UlFl7LmRdRUl'
    b'ReDiRhtn+b2A4RJIjGDSGYkYfpxRFjT51RtW2BZcAWsQ608iz8wxll4K+0sRt6BOLy2zBOVKS/76cEmeDPHshE4t8PDpocDHCdhn'
    b'L1CwSJOx0duBMTdBuZvyUm9hTP/AGK68siPL0mLv3Yz4ssGoyIsg4ZpkaUZxSzIRuXokaaLklyceAHxYQRC8XI9k12kzoIPXgzCK'
    b'fa3Rqi+QJ98YphJBUp3OKoF7G1ieeH05zQYGkvUGiCmnOn416nF0ODX5dw/MJt5U6ASHP09PFKs488CVtfkHT/1bh4PMiAeiIRlm'
    b'RUm2mwoMJrAKobloF8cTFWCBqBdtirAf05bM1MP+Wdrw49oCu0mXLZiO2SGKONopjJGB61twKEvShIoIr7dT0Tt9FTh0IhrpY/bd'
    b'yOUAaVaEwxN28+mUfUo+sC7ujYhO2crFgwe82MKeDnzLJbswI69aQB2kFqUe6YgXjztQOxHXTtfLNsz3OXGAPZNGSdMhTWkLw2uO'
    b'tpc5aQrN6DoC017MxBmDGVScy+PeeUicsjw+T7X8WerZasBjIqHzBkHcIvaAJTn2jCJOMAW31jfeZVpsIYNZuzG8WOuyQffvVdba'
    b'ZWUVZRAELfUUbOJ6nRV2ATyH+JvUZeo6mVPnBKoxO4DMgfCa6CmkiUZlEaU/b7N2F0GIRsMFvYIUg0oIhuS/1icpB4eDdQcTtoHE'
    b'ie5glCbUpXy9Fsml1lMOSKmeQDOW3Crh4dhlourRzfJ2cYPwT2ZHn9j7G/v9ks1nn8/tTc6x0AXpkYfURuwJgzOOOACCUKpYCTVA'
    b'qVDhQGwJhknPGxukhAGMWxN2ublInMQVBJYri76bk+e6BG8TUt7VHylAE4DvzFY+hLBw6Q7HkVAH7OOOg+xmhHVHJ5hp4FY70KbM'
    b'MZx27r14VfAnV/Lr/TrSu0JMR1vbQ6SBM6Zg/x6oM4jVr9fEat7uFwqWiDFihHCRpTyBfWKl8+O4/82xi74cIt0f/qAEfuLPQozM'
    b'yvbH7Vd30Xm+Tas6K9pIbx0u9QMcbcpN9GKjNO1qXJx/ma207YnfT2V9O+kAZc9RAqqSkjhEqXSUVrLWQ6xsMIvXlpAVX65pYoux'
    b'HMCUjYDj2VovqEqTXIzFbDuqnsMzTXuxGI+qOlumUXxeXgILOZ7PQ83QYWihm4ZzAztVLfhKLCeCpi5yqFbuYh7qSU9YjLAgeev4'
    b'C/1VmWQt0NYQkin+D0+70MbrVU4sB/uU5wqtW0Rnyxi9LqiAwAlPA6s5GiUUcbGA52HqHtx124soz37eZgmcqXfox4FRp2mBeb26'
    b'OzWq3anLvo7UkLJNtc3hZXn/vgJAOrtL6ji705p5QXi6WqVxHa1riI4seglAtGuKbJHad3BQgyg0+w3VA2DIcKlucc++wpjx3rD5'
    b'oWKdRuTrYOSuUafPDKpwLWLwcILjXpNQuaTAWZLBik5C69PRxrhtB+odPd8fNrTxwW5ryDvUppsK5ilVrN3AvY180AtYw4tsfTEQ'
    b'sF3fB5MfWiBEZsusQl7XC9jbyAc9p1TbEEyriOu6vMqKdS90byMfdJCNL9K4HYgOq3oXbdTpGsU73CFDicNoZEBvdk0LHrzRss6a'
    b'rOmD669uqq/iugZH/6usQAfktOmFGm5iQL6K66jM8HkArL7L5Yc+wMEWBtwkXaUFRHyI6pJfAnrgBlsYcL0HWRBm6NhT8LJCnPh1'
    b'Coa4Od6n+0fb087oY1sB/mNI79dgSLSm2da95NbZyoCfx+cgiJarNi1AFdAD2F/dpGBHEgpTr09octYrJOv0rVyHjKTt5uNoV+4g'
    b'q9nRpmP76rWM9it4RG2atG2ic9RjBQ9Vo56lByaVGOaL6ITi1DTgtOu4u7moYLQCdZJCVWd7t2oHJK7gO9rsA9NsZFJqQDQM02pY'
    b'lvRB1WXAATAtkVGnCEsGPHEESH9t8nE5uuoiIrdyqG9LTBwC05UsOyD3oqpLjNROpyqDrdVxFvEKZiu81fY21Ws5vT7dRHHRIcBo'
    b'dYy2VV+3ooLTCiCu46q7pahkngIFnph5epl2bCWjlq/9042wmO+DoWqavD2+2MChlYNKq4OvG9UMCKAhb4X8g9pLfjPQ23sq2e7Z'
    b'I9BHR1QxztO6DQILVOwCiPTaywl81UMQpZw2HKrVJATZFKkGQ/c0C/WghKvh4O02Idj7iWR9DS05fVmXUdPucnAHyhWBWC+SqG2K'
    b'kuwySzATrBi5+R6JsYhtDdFXC8yb6tfrTL2qlymbz55zMybxjysvQ2ILKi/37Qcz2sxnL+Zck8nv4np6IP8xCMZoaMUbQJeqCe91'
    b'cENwEBXSBHF0ec/QMF6MT9YQQMXnDsEZhq4hcgZhjNE3DDmU0Sa7ThOFf7NXP2K1UzCA0PS6rdNNGkFNB5VjR/ekW8qggRWYqVcY'
    b'Wr9wak+wigPjywU7fi5cYPqw7Y7rY4/tmTO2jvEZOERA7mA/6oC/WrDPvQNWgx7RuD7qGJ7DGDidFum2rTHagz2eyQCSPU+L5QUo'
    b'LHhupp0KEBIqItoG/x8yBFytXYuukf683JYVVw2B15/5HIJW4tkSYpFn8HY0qtNlWSeNeDIgm5W9bFVCj0+uBWAwAZvz6knFXY5W'
    b'o9HorXTnADxo0eB5cwgRClFJIfhIfQnRzLK2YWWdrfFx6TxVCRAf0Bd6v/h1/udOeFDjEOVjvmH5OfqJl+olaqwIcVanhT7IG9Ho'
    b'RAK/7e/uN0GAkQE8GZT+G8aMPXWMODmlKgBVLbQYWHdDXokP6D3/pZsZIixeYK4QbUkRelH2S2jo7pbnazdfNBNPvgc0T4Q/FQnB'
    b'M3V3nAWdxmQ+jbuunciZGfEkzdrutuo2422RDfKbGY1G36TSxUmkR5RxCfMSgxKmKE4uUwrUG+MzKFvC/4E9OAJ689evp+z9735k'
    b'z+fzKXsbN0n888ER/P3ym3dT2OEYyPLACMVvRjXMVhCHTWcK2yL7bbkCdKgtGdr8wHMzt3IAMhrzVI545Zoyb+xP+Cy6446y8MnN'
    b'0CUzfEzMhKTao3zAKSI55Q/xfGh33td3oGR9m8u/ZWKwkWEb/Mi7vcUv2UiiztfWtxd9nyW0rRcagYMNtMrqpoV8nUhc4+ZEGTvL'
    b'tcazEPmYme8D/l3GZCxHCV1EbCuVuqSRFtEq7YusBceJ+WmWl1dpPZ6w/7ZgoyIuRmc2uUOHp3MMfYF9k30LX3l7XoRcY1a/3RSk'
    b'BxbMQyPw22FzUkxczYqLLmj41T2pJk0Lzc/F9YcD91ycnM963dxg5PRb42wwsF18NZk1VZ6149ETO8QgxyiagdWtEexM/0dTRfTB'
    b'fzmucNRegRtKhO3dZZw7NkYykw1UpIVKU+6kopIH2fSxzD64eHxZ7BziaNysh4MWkZ+k+qln5Lh0XBCHWwMBr1lIDmxtZMtYh/bB'
    b'QuPQxgaxaiO/Xii+rZBlVbTYzsLH13Wa9dsGaewUTBgfM2H2fLAs8zyumpStt3GdsPG3kHfmXXq+zfKEPf7imNUpBZEviymjpADP'
    b'D45fTGaPHrOXlHw8e49RHTCt7vjdtoGwEQyC6k/YKm2XF+iiDZGKywLj/tfbokhrymPelqzJ8rRo892jxwwIAKv8+vl8foDnPkXn'
    b'B2fSKcvTGOV8TH7Oc/nKKNUNG0PykiePHrNgKEb2RI+a/+uCPf+CjKwmM/YTCBuQuQ0sy2WE1vYiLR49ZlVdJtsl5AFg717/8d3r'
    b'9+8ZKHvQgnD86uUf37HjZ7PnnwBpHz2bff7JlAzJWnilpbDPx8+g8Ivpo8fs+ItPWJ02WQL+6cu4ueBZAwq2LeBMwdTReDdt8jS9'
    b'5BdXfJ2F9FSQswDTJ1xkVZUmjx4jdiBh/Iz9CRTHFzsNayDg/Pri90//wOJi114A+lZxzTMfQ9pQ2EexuVCzR74Ex2zBns3nXCpE'
    b'Q7QIMw9hmA6aJTnEe0TBrGilBPgKmpJPzdVF2ahwuJyMYcQwP20OY5HkHhbiGnOyUUR6yICdtYAWlQXrQLPaF47vkxl7RWJsQlfD'
    b'hjXb5QXjWZU+DeccexIkpk9Z02Z5TqjQr5qU6UITLEXEbCyYMm7nOUU7z0lngjlsEbyrkX13U0NCF6zpk1JsCcdJZ9rUSzhCwCu1'
    b'jbOiGXdmYAN+4LLO//RA6UwC60Axbi3gzYNpOMnzUngzkFETxg2INh9ayOggnRm8gQ2Q9jA35akmcqFynDsAjkaj7wEhpQB/IG2v'
    b'DuCuQ3Ra5duGUY9M2opnRZMl/JKCvfOA8CHWmhXVtrUY7PHnT59+/sX88+dffCG464uDo6PJiaTvPDlYxkvimgwYPPi9EL8FmUEh'
    b'mcbQcK0IbCCaENEI3weQPxLYW8V+/f0Xn7C38VsxrfHR0Xx+eHR09IUW7H4CqhqAhUBw4nmuWcvzHO6sgLd1tsogfR7wKmRPwME0'
    b'TiqwATwfwT3jAfHHb97+5eV3b76J/vz2zV9ev3v/GpmxGD5Ni222TcvOwUsnXX4AFKRVDPsy3+k7jxOBb+/xIu/us8ztxOZTASqs'
    b'7Zcl11r8CpQlrN4dh8x38CD4BgPkaupOdb30pV7NkuvJlB1xNw6RVtpOB06dDk6JbhjIY6x/ZRJPFoSYaVYZEJ4MHK2BDm3cnN9Q'
    b'X+nPGmTRJyDrvCxz2vKYWtftFcoU0GV5GfBdEcMA82RqMyIKHw31aDE6XJaXnPvghvUoQfaMZ+wqRcpta7kMr9IYMjuA/FCnQcdh'
    b'bogtAiXR6pbr8ehrGCkc9LKR2oUoaazqFNIhUe7K2WzGScNIQGmEC/JmqDTzQBhlcBXrSUvJV7/A/EqQKYr0IdoA8F4nkyZiBGB/'
    b'SspwHkVI7jUinTe0QrnR7gaCHUG1R0NyO0ZWbqqsgKTlEKUImLE+DA5OIv7//K//DWmuYF0b9vXrQ8hndQjZrA4hl9XBMo+bxpcR'
    b'C7NhkZTymEttJBg1oBlvL+q0gaC8MyaRA0LsrmHLPI0LNi5KbeR44+aw8nQdL3cgQVVxnTVl8QfmRSNwUBLI9JSUM2P5NNx4VzG4'
    b'PnrqylsDZFiG12UXZBt7JyRJCxCxE3EGKH4MZ9fg4evhcMOdkvNxW9JbCDBw5JrYCraIJhvZQRz2VDTagVdYIJc43tzldsADCiPo'
    b'aRtW4UAOzglQZ6bX4MEK4FUiTiLOk8aCtWGX4ocMZxeMVmCHAPP144RR0yal6oOG15M3U8+mF0gpRmeLSVoGCLP+aIqZT7VXQV3B'
    b'6tEs40kTZ03K3m0LOMlfw9mk3e6B/Bafxkn9aW8eTnk7LUqhUxc8Pc35AWvRmj0cQpRdyYqfRDORKtg6rfJ4mY5HSu9shkwB3mo5'
    b'eWrt1atN4OWG1OMebTQC0VS85luMrOFT5HbdSh65nrLZ1Xm0rdGV7qJtq+bk8PDq6mqWkQQ+W5abw21zSPhvm8Pjp7//fP75IS8+'
    b'qEkXAg8T84O0Xanx2TH/nA3FOxfR/ThEDNKeFetmzAcGOTT++rX1WE3tsqvz4U+EWlNDqW/87lDrG+3l8mq/nJc1etzLChyn+bJm'
    b'WXIAEG2x8feQBzsXsEMmBrZO3cn6I5m7LX+FvuKqynfjPN6cJzGrT1helh+aCNJ9gcoQNBVlMa5VD1PGY6AgKsBBKL7OmsWR1YsZ'
    b'KzH0xp5dncNZEL64T+4eYRH0LoLwNEUR5SzS3bvhX5NibBVkuUCk8Nvmu9opInHJc9OnkGN9SNBIqMk5P28vgrJeZR+yKk2yOEK1'
    b'oAnI2WQ45ur5fA73CZib1p7z0oDhjGAIaTGTTWZlvT6EX4ffASstV9H7T45f/Bg9n8/hHbWKiwwiMXsBUgTPLLlezAMVZMjuxeg9'
    b'RUd3K078s+vhl/sRG0IEIQT+69LXQBpz6Oz9736EdfBRWP8aFngnf8gVVK/KvQv2rH/BOOcdsmBFcv2gy1Uk11N46YPpHD3kgikM'
    b'dS9atvIJ6uSAFtVps9x2COd2KE2szUO20uObESXMPFOH9i5vHUDRga6DpAf/aCsQtH3p8KNwk0EcZTBXgX+T3okPpFpnHQfxG96H'
    b's3S0ZBY170HRDlUT+AO+lh1M6a5EJnfiXQitSK4/Hpn1srxBbG8w6wtTlZrlx6Ip1YOzTmp9PhpV9XBOHQrGxNKZntOXJAcVWtRo'
    b'EYxPrf87T1fcPT/l4Rrtf0PCXmvyszd0n/cG4T73i38o0/O7EorwMDi3mgwBmIqZ328cE3bA8dFz4lJn7oCc2G3i3+g7JAOxZCo7'
    b'vNAj2rHcZL8jrq8VIdq09YUAburNRq8gw72B5jVKwPTOCPzm9mWe2r3KOCuEs6x2AXHp907b7L8SaEBDV4P/KsSrz/U3ImG9S8/d'
    b'YQ+9JuBwj53wvj897oBdYdO9MZ17Ur8vN0BIbfdnlFrBnIUedkNPL3wXg3rO0r0Nziqgmgw0zVUKUv25RfhLuEpT+EI2DP8AqlMx'
    b'RLKE8Ox/Y++j3u9e+8aADR3HCexOOYTTX9Wfqie9A0gbPKZRmYasnlnFSVDdYVPF6bbIpqLRmYc6jNj6jjbHgT/6I207fNUYuOdW'
    b'I9RK3xhK6tupehAT+4tjyAk3ioO3d96kI0yhIUOZunFrFJqWfK3PDIzC5KSmqEGHT+oN7wokOFgDuSnv/goIr3zGIx6Hpz3lsfHX'
    b'r9khg/c/dsjgBZAdMngDZIfs21evv2OHLG2Xs8mMvdy25cEqy1uwkd8oYDXYEvyBW0+g+Ql4MZJhGL0NjqE2+4r996fzrycMksIc'
    b'pNe49RN2vqMU6DZP0GYWZg3LyuQMqtF9GYQPksMn5rOndr7mTXx9J9BGs9GUPcXITD7jSZHzqfr78KBlxVmQGMDpr/Kv+zEggrwf'
    b'/6E2D8F+Xskt8bDMRyDH4j008Duwnjdvv/1hOOvRdpHFdDxUSK93Lv8ZInk7m1R+GCyzaZbsDya4DxTaP+aGubjiG8aQpn8NyNZ3'
    b'2TjUw34bh9o8xMYJC87cNmOfzTNIfqYimoG7g/CnsYZkBDLo4ZCQBbXdFv7Xtz1FX23Z3OMMLZfJlJmWHZ+rgNf6zZslRA410P5L'
    b'5rOfPvmN3sk+5t5yLqxpmny0i+rwlbY3Gwyrd6vto7YBsGTUK2xez0SQe3JDgDdSXFKOfTT5DV9bkXCo6uLGT0W3NI0IDJD53oQn'
    b'z0AA/86O4lWb1oubDqIO34Uhi9wGU4jRqZAu+dPDTmqbbcsguacp39SYg5gySNgkTZkuyqvFCLJGKetDzXSgx86kpwX3zOPE3+bg'
    b'dal5DKrWmm7Z+O16CgpGQvZW0fXIslBBQ2Iqg6gjAesV3lh0J2CddUIWZlLc6pZQIMxuoSKZ3Fqd7MxOdkYnu3t3okAj9vjYBd54'
    b'LzaPv7MvsjiM+Q3oLt5Lkxn7FvxGih1Dyz64OHFw6XWVLlvX6wSs2rnPDFf7x0l9AEfIBDwYVltwECrREYc5Bp/k26KBUwbwZMaJ'
    b'JpV5WdYz9iPaxXKj/aZl67JMxM0RjP+VVeIfMOM43PmyhsV5UwqXpSk+IbC83CZgsx8zTGkOQSCAN3FgpjvWMi645T4IDhgPQncs'
    b'km5F6J/NfhW+UrOhZ+pdztFBZyemm+EJjgM9QBXn5FTtvloM6KbzSFhpZwIS35l/rcfrsmUai79lXwaZ9Y1vTLeTP7A63aJnPCeG'
    b'XmPwYA/jG4mDWxqpcH/7TnhYEY2A2VK+k8lVL7IGHFBmvmMiIP9CBimPCO3eswIq1cAMNCS7riUn5BpooDuoOQ7aSh2GbQS50iWI'
    b'3gJEgK8WLLCSGpq9jpIhuOZqvHz7DVh6XnBfP4tDMKR9xNBCW+3JLAj9HXAyIC/Jy6QfJAoZKCCQN6bmFxm37Krc5ol0iAyBB5ai'
    b'PBTfpejVgIwGcmaLYC6HzjzQ6TE9CJGdR6dtpvgYvf+QVRXMS3eSUtbWqBaL6+UFLIky3+dqw0PQEh7E2zVkzdGHheMRxrU6LSsv'
    b'B3LmoAA7gsw8JtUqh7KSoKbM5o0mWM23yKeteEnTSUSmNzVsj1PkCbsxgFOCZD63znR+fKhAXTjgqZZ4bwHOe2iLZ7VVVbjoDVJF'
    b'WzrG4uFsg9si01O+w3aQQmiHy02TkoM+T6Ci/GyQ4qJN1izJyWa3MmCaeVMqTxp2NyE3DRSuRhhUCcbZjCuyisdYSyKVeLeduwXL'
    b'wAJ9IDw08WU6BA8kHUC0KC0npyKi8T4ImYRCR1E6PWgAk9QWqroODosgq0hQ/tSPgZXDRBqU/Ka6jugbGjxbkYRgx/iWjyMU8PDI'
    b'Wc5k5XFoqPocFGyQyYr7B7pprHnJZNb+EuXlEq/HY8z4I1lbkxVNCy4dUJtL6pgq8ftt3mboTqhNR0sfutB+gJExBTYV2UHmZoig'
    b'lYj0Q4lJCI/CTQ+SC9xl8WSqgr0XD8Jf8AX8R1jB4bHDZBMeyAfj94y+0ZxxxH8xtitmZeRIGrkBeToyfKHzpkNOGKLH4+Oo/Du1'
    b'HoSfp+HgGZqPZHfc/1SloRBenFbLtgGiXpbFZVq3RNN4b4HPWbEq6bbZNp41a8M7pXduXfPyzal7PneZyzCy0nOIcdMzDBuaZPG6'
    b'KJs2W3ITPte1tDeRrlLo+vLjgiEEvShGXod5qlXHxYc06aqxygoQjsMVPqP/gD0+99Snbk/QTLIrJe9oNHp9XeVxVrArkG65IHNe'
    b'l3HCrei0STLQe6NGFNzNuQ1GAv6JCOwnuLhAPAnkJwcCvfAImqQQ/eKEZS3jeE8btskakIQPmzbG0ILZEq7Jyws+qx3MGyKTnefx'
    b'8gMoMKd0FZFxTQ8vSwhzm8OflLjiAJ5i+SvuFIRaieIDdOGElSdfflQ3yAkrCxKSkM3oZf2phgOEZSQaHpgCOQRKBJ005CTpzd1l'
    b'CqtDCRt8izyaoQFYqS97B2ol2bzluSjhorHQaErL9qYR2pA0y7wFnQ+oEbTiLmKpw9NNSP0ZekW7Ablnb0aYhfOEzfdMKPeRkY7y'
    b'BpGiEx804CffeRh3xXEIJsr0BPdTeAjEW0hWg0MtyPPMjrOgdZ6sTmVkhKSVr45GMieZxcnn9lrhU49ApcvfJxpH1yqaLH6imLpW'
    b'x2DyVAXgnwvNP2l58NEnkkEdGxloazJrMNsqxLyQ34xgpFmBAIyc9yDo1dzIIrjP+Oj1kdCn+w2Gw7DHwz93D4mQZaY5x293z3M+'
    b'5GFOv55BKjG7PknTEwq1R2kX/VfnCU9nDQdflMS7JlpugXbhNt/FyenOoJqNpuzomYiksS2iFJmrtYlMgBg6nqRjFK8C20mT7jhg'
    b'/ajQu5Ly3GzbLovyahy6Y/lbSfBWHf6XVxxUZUom5N80hgeZ4+rySsv4KsnhDJO3q7sUGjIZjA9tvBTn04J21uUVSche/kYmURgh'
    b'0WE/vggqikJPATCQ77LMJ2eedRFZIEXe6/JK+GQp0e5lsTvTvLKADiN4PVnK8zBrAe6VqVkR+9pL0HW6tLYVJKRwrFAsAwJxqzSx'
    b'BAGrskIzXQYeB7hG7qZ4DEaUoT/xJY2PkHiYVo2u+zLrnsI48SyCbDOwMHCnZgg+v1UbUtweahIFAl+gFj3aAHH514QRyQI41xDb'
    b'aCaXcAyP/aoTvQDSGO4aLnPJUTgylzHjrADDbr5OfHeI6nolefhpSxCoKo5AhX+DryubbVLFo4Ui3RIWJPTyMcHRgbudD23KRtX1'
    b'aMK+5DvOZIASymjKIBS9Rsm8nwReOOroErP69nSk6kbH86SzU6sqhCCL4M1iPp97h4EVnx/3j4FXhN6/8vceXwtoaNf5wjvrJDra'
    b'DZgwVOvsiWpgP889/fAQaLwj586KfWrdi1OIj4CnOaMgUx7oQHURXvXUTDhJCglDUp6cnSJViOwiIAQnqV7ModaUHpVACatxRNGJ'
    b'fUjEDWY5HcWXcYaxJ6MVJBRYljVkhFTKaogkYk8pBMuuZ4EhZFoRcOlxa8FOHX0UMCvnIxwkUADx/OI16tq8D1BjMRh9l9mfLKNi'
    b'p63aKKqx+tbXmtOG6hZ/97VS28P80DtWTuz6T08bb7xgQKXx/SywwCIUMHVCrk60gBRqg3YOHFxk0URsVAYJNqhBY7aaWBoiLTqW'
    b'pAJGz1kig92os9CjMzbBcY2PftpZALWDzc43ohV9ZYnOof6oVqA3+2ncHSY/iKl9XV7xeMtYubySXl0GFJVfWPwTctMJx71LHWSe'
    b'QxnBpLSlItF76EkY8lhtPPHqfY1tkx8LiieWvR9OVigUiaswJF9RJ0h3K853q7KEdEMmu+5uyRmmig+mmiPx+1rrIhYRqmjloeA+'
    b'ACAx6fmiNUFLSxHdJV3paWa8XWjXPOhD/PC00vcnn5J/m3tndT068YlPnqqWBHPSJwx5QHDu7DQVJ7qniRRvTsKCj2+wyJlPAvKL'
    b'p4E6P0+6xQJPW+fUO3FOvXAr7byTzdS3jt4ELo3f4frijJMN+IeOkXEc6j/DtXUE2p98CwTaI2K6oxPOfc1qpCWBf1y4grwlVkA6'
    b'YMTGy2W5be0nQ2oGBfBsLh5mT7v4ydQcHz4fikhScbNMC9TnnpKds/p/nm8EuhqkWCbwZKgBV7ly254aHZ/NKO0f1SB9NeacIn2a'
    b'XhU2O3RsGJnecE0TRWMw+3HDV1t9Qda68fHc7tSJn93VMWmjQVsml0NoyeHeCiZP5bY1EiL6ZWOqD5V5Km1jebyaPgo36oXGg+ZN'
    b'HKqh0WshXEbGGo3Ajqetxx8mNJ5LUvZ9mLJLVCDodUHXsmnGk1s9Mam+ED3AjLpeYIYQBOFZ9YMCvumJyAY8YAxPSGaYaopAC5hR'
    b'QHuV0E3yV7jqixvexemn8PPTM7CwFwukFXoXDWvrECE5G2G8WdwggaK2VnWhr8anZwKFk9OTZ2fCCt+wzviI7zBk9GGqc8F+UgRK'
    b'gQjIwccZIm35ZPsOwqSTRwSaYJ7v+IuteM7kvkmoHWz46+ybFdgpc7GAmzNnlCMCX1Xf/PXrQ9EeLTOnflM+IinDq3fKXW61DyU3'
    b'sKa4t+k1vBFkLfurCIPDiZuAfUhTyEQRtzSSv22bNlvBm0JWFhCePGv4my5Nt0435SU8EhZLSKZYtJDZgUZO3JfPHqPJa7aTZXuR'
    b'1ldg+0q25Em8+7SBmEM8FM+h9MeSXl7yzZK/S7YXdbldY/4sDTkiO4WV9IobW6J5UECwVmwL/C3oeFAWGMTKynNwbZzoPhVOnoGL'
    b'uFGBivgTtpkgwKQ8KykApBTwNNI5TcA/0QSk7SgYEbca17If+Ea2X+oC+Ocf7d0yKfgAgZ29pOV9B6E8T+8KQo/0t19LO+xcX+oH'
    b'jWx+x8a/ijUT9oQYZNPiWYLW0aeR3/nubD8TsGkJJ7R7CSNiP7756QAyL0NeItiYEAwA3Uzg9DRiP6H/iG5tQLzw+zJRHrkHIkw/'
    b'ulYgb9AbIxdBwJQiAZJ8bjZpQf3iw6VcFu0kID9kkWMHwsCXG51n/PDDe55EYibHATG/aeVOiCc641AA8h14KjQp2FQf8kQtRb5T'
    b'wMrV6oT6d2eDGXBykcXC4lqDTVRsiuBv4V5DFU+yCJE8oNekIJgaYpBJBobIP1GZKFAO4ZoyMNUQX9Bv7w62G3x0RFg8mD8IdV3v'
    b'uMYmgjFpFDiaqGRsgBS9SL/nPESQRz7cEYiOaqUSMvLCaOx671M2UhQKv6DZrQvNGDGWgqZZraJKNhiw+niQ/BqajIVmFj2SF2+k'
    b'aIM/rMEFJZHJKrCxW0mDKrLo4PzqEn27FqE0Honu6CdwD5cWlOUVW5FwtI4eSZ2pbKUjXjyekFWLL8OIFyr7HUdk3trJQ8y+NErw'
    b'geybsHadT/A99lfe1sqrigPjA/kA1p4LnohJt9nxzQ4cHAL0hZffPcyKvKPAy2gfVcHNlv1OjcVMySLuoI/CN2XOvOA/+o3U4GDa'
    b'L7uO4Gmhm7Y+bguoQ+pdzfja8Z74Lz67QDuhAobmgFLVp4Znra2oby4bKV8NexKFX10T66EV9cgdup9L/JkqfqmC6JLndYMjv+Ae'
    b'1LbwOlnRapoXYwS20sIo1NUv8E9fgSprI5Cc2l1UlIg/c2o6C0ERpLFullxaJM882L/lyi/V/MFyUdMYBhBJWpBNDoRSyXO8z7Jm'
    b'W19mlyXK/wfnWQwenULEYcuLOM/TYp3WmoPa5LfVb/DJy2SEsC1NHQfF/eDhPnRyF+EH3H11OxVsc3Hj7h5L46HtDQlL++bTaZTb'
    b'VvdfGuYeNGVeVYRyYrqbe9C1k539OuSxc72Pw851v7+OrMIW6u+gt8617itXidOLwgLyu1ECaoo0icoqLaKGNj3shH4NTkZbRpeF'
    b'4bcmCP9QpYUUf7GsI4O8wXDQXoFLHzzHiCFxBR2kutGNk5SthPFa8/M2TX+BCBo0glMauNd4jTM1bXzLHHz2+2ASp30FdTFtwwDA'
    b'oKN+mfyNUaNAou04+Vs0bASnGrCBUxMdrGJ4j8WIhqK3Q5q3jLMxN8NsmM/SBgy11EezuSBJXBhTX6SNA9pDDdD44wp+poGUQzgt'
    b'qllWrKbsgP44Uxlm+Ml1NJubACUZcbrRGY6sY+KFts0mXtYlZw+g4gkyI+AdykATPhJaBN0bPpQAFFnPanSDfrUqURt1y99VAfMP'
    b'uFf32Y0uUfr39SCahKZ9ZOkhp8Gw+zad2r8hfqIVBu2BCWdU06AVaaGN2ZPft5D+8nipBYecT0DszXN4sqvL823TRr+wJyAJR5Bc'
    b'kIF+GNMdU6iKizSvwKO2Ak8lCfFZbEGkBMDRVZqtL9ooP4rAZBLApk2ZX4I/9jrbpBGvtoFTpsozsFR8bPfIc/3Oqh0bY0APUIZv'
    b'wM0K4vls2zQCdcqqzLNSwPuMnefl8sMEhtgxbRpdmohmAK9sIJpI56RhE8Cax9llKleJm+jT0XcCxsOa5g1r4ClKBORzFqSWDn1M'
    b'2bZdakF0Le/aVpOT9fsoXgbbWdI6Rt+efWaMULoSdpS7QHXvdrCe4htgcIpJjUlB+ChoHGWJYloWKzFshv18cMpWIxwKcbHoRkIV'
    b'kQIQlaIdpCPUjFemmJWHINcpluJDYJcPvddtV4E0rx2NwzvAQQeJoPMCjW0lpwiRIcCiu7jXzbWhx3uqO9Stv4obbkf8WMT9+fbd'
    b'62/Yyx/fUKCdD+mOjS+y9QWI9+D/l2ebrJ1MVbrdtmSv3v+FNcs6rrjHMawQNFwwU/+GBXGVQSFZTYk1E020o73KeLIz8wa2klkj'
    b'4iqbNW1ebrNmlSaYNwLAHBJNHJbnTVpfkhLavGqtRv8i6WahkdDv+NAWN2I4t78D2ovwrFLqWvinEAzX0rRuYF6gmxj9uUnrg5fr'
    b'tIArOxAcRBzbNmkdxfDxtiteQwPXBphfBAcMR8FUdLHQuoLbyCYtt+3i6FjL4YskC4FMUGlVoY7ZuhuX5+iRH7cxnWIGnqbs1KIu'
    b'yJV47snzIDaGsjQpz63wgP5qrgEg/CPKPvE5uIX0T37LU77dTvbZiC6kW3nGNtvzJm0X/q0nZ5isDNMZqjxxHcC4ZxFoDhYjsHsb'
    b'+QDqlyudfXn9LsU/wNcMDj3MjolUh7/cmvdhU/djVQ/BroBVfetlPhTKjIcARdahmAXsaJtbrOu4usAS/Au8kP/F5Ai03/m2G767'
    b'jZ0NOhZ9V/t2tLmbZ9BEHenxlXYEgclUVs7et2Dw8eaHMVQ1fY3q+GrWXMRVenp0xr5kxyE305AgzvvU1AFwpI+X8tVllpdXaT0m'
    b'Wxx0nNKqKxNtDAkGfmELvfx0rmoI/Z5d5UgD4rCPPmNiPx+p4yt0bYXeBjGAABsBOHLYvYA0HWMvO3kwNrIn++hnG3dlF3djE2H2'
    b'EGYN0pK4w8jem8NqL+nuPri4H076cTOMfe7BADpr6aoKzizbMjrP8hyEiLEu9Z9oVxmPzC8NVvX79lAllseSVdPp8koYKQ6falcg'
    b'fDZN2oKYM2rXsf42K01g2SH6K83mfh0xJRooimiVxnW0riEoLuYgG34tClhvDLr+jMyuB1164MlXhEHzXH6m7Eh/8nb2CY+EN3yf'
    b'mLdZaj61FEnC14xKQ8GjqVTsB48ShVqTuSuyyq6rdufF2SIgDtnDjPe+WA3xQzbTl8c7oDJdZnj19m307euX76I/vnv9+pvoz+++'
    b'UyKEVfan1y+/ef3uvZIoXswn9jUANXYLNh6Lrsqa3dxOCJFIXXGRcOJWj1ejiVEPbhD0SUtxCSIBWJEK/Z0lfIScguDfXvcC6IOG'
    b'AZ4YEIuvXYw2sLEH3hK07YvBeuClNF6lEfkzKvBgbuK5HhhfFGK5CdSCDcCsQKfVOEL7cx4Xh7uVy7hcdl0cOtjTqKHrLWlmpnio'
    b'erH9x+AHKLibIi7EMzBCmHysVZRjeaAV1Ac9bNE6QmTBmytuUMFicSN3SKbK04LKw3yr41Y7lF8Z4NUPaKM5shvVHYSdeYUZt1pX'
    b'RBkutQak2/tLs/wl3w1z1yHT7X197peakJ3rH7RwhUMk0Pufqr/xWfig56AG0Ngx/MIn6AU0hA7xCWnzPC2WFxDEjJ9I0pAoj8/T'
    b'3JW+KNhqy8PwSlNzvMqu1rMQOHxeHjl3XbHIAg4YeKFKHPP9OvLnCJSoJ+8xWe9Yakr/vz++//HVZGTBQtlUhQ4RUd3ob11EFVFS'
    b'Rv/+7cmNNQnut1DW7FPs5VM1g21VwQxurX4duPT50YP0pMnKqiUPzrPnI4Lv1vBbrSaexJ7nDxkeeaQ6Fsm6v3/56t0PEax/9P71'
    b'uzev35+Svbp+n2sG3XlkGCbvbU/kXvHxRbGixJtwjCo2VXA9R7ieI2c9tSsGBbDhC4npucc6dI3hpUWzrYXVC11NkkhzSDHQeKoD'
    b'4XiiTxVclY2wvVNjPnJwsrr2EC2+7f8YLWq4r+ICZmh5iPKpvXY35n/BkwpEoaHYNXTtA+jaLZnkFgh5DkZ4WCBt96jsoqyzXyAr'
    b'WVa03Beg3VZ5eirjOOFMzqaBELg8tCUcWfjerYdxwrfmcEBZiolFzRP+qm0+JO71zM1tbto5vRRhs6gsorImy8JxllzjzVFZLwrE'
    b'qGi80JxPoXfM0BFchYtqdnWR1il0ANs/aeeT0/kZBo/CikdQcc6eYG2OcLURjiCqPtiLZoluQuXvtIJOSTbn2ABz3kx0VR15i4/E'
    b'SFYIYMHmsD5SRF9lRQbRj+YT7+ej3lEJCj8Ce7Q5O2BoM2OgOkuuaRydND12CDhEvAbhmiGaiWBpzChmTBlYUw3bRjgA1avsx9jK'
    b'CNU7k/O0vUrTggyQPbNJi7beeWaTXmfuJMPTust2+3tuNDFt2fZoj7aEmuF7VNU7CtY7OOI6OWdDwYZJ2vnZRHYlrGa08GRkseXf'
    b'cgTgSAA46gPwoJsyuB2FaZY0hFmV9VVcJxGnX/BSii7KHIxz7x6iWQDwxU0efgrBl7iJyhWSx0ng5GELzZxciSB8z3nCEMoGVoRm'
    b'a4epLSZmY9ij8W+BjXYzUhimT6MTzi018c4uWYITbQyJJNDeCPyiZnPSMGAjCK9lTlBKKfonO+hJj8hsZDYT8LyKHCzhFrOGp4ta'
    b'JY0cjSGfWqyFQIVYC/vSilepdUB6QWWRtd2AewrfxojBNOEI1ApAh0gphNXSQVRGFHKasX6LHxKiUZigUJgSedHS+KIapKlKM1vy'
    b'hYa4bXp+cC6HKzFaBGSj+sgKCJz48OWCHaUHR/OeyI8qFtViwV69fP+n6Md3P/zbv0c/vXn1P16/sxsbuHyyMLvs7sgnYzvBGIVl'
    b'pCsRV9fkQHLtpUMhfdsp3byvTuKM9N1pfPjpJmp93Pjf073OzH7C5kwkLKj0iCZ8FgDCOfS8Ux66zMaOs2uxz/jvOuVNgP8Bg5On'
    b'otH+0OqWAjeZI/mKKNoKi0l3pW4MYR0fhoazN7NTwdUlMnzsXcxY8/wJsHp1t9SWibokXMlC3Y3IPR24uGFiUnjnCLGUXuXKKq3R'
    b'HCvOIXoHUKR4htnd+Zjf43AOvE8KXmw5PpcVd3pWaJY1+aCVsTktEJ9SLxxVM61XwNaLZWrCksc959u6JpXeTY1Ry3PTFAm6fKtl'
    b'zQ4HEzv6Nj7dqXbKucT1qryPc29yKs4kjyKfFMG83OeUwT0X4DCTg04cPb49FCXRh5UqTnz0bQG2lGAxgy8qS2U4dDqCQvnAFW3b'
    b'Jeg9FQl8yArwy3bxBjzI8Fwhlky7UXD9u0hTHsnMYDpUvp9kJQek/fJKWdF9jyTOPXmS3JvR0WZ0wo6Ppmz0FP568XTKRi/gr6Pj'
    b'F1M2OjrG8ufHt4Ofqtd1uSUX5mSGf5/vxvoKk7deEYvIKTwcuSQAZJ2n4zF31UM3ecXwRlPfLiGv9cmUJXyaEDRO8Fh5ahXVbJln'
    b'leXzX1YNxpiTzES0Q0nu9/MJCnRTuHCJKPaQfQ9mBoOesnVdAaHxeRtGR+u6GiqqUARwaRWhwUex1hJbZDHoa1VdzT4H4rabawTr'
    b'fWs+xMPFnGdvSpEzgLpEXw33ZRfzNsFNX3R6miXXuN1AD/Elar1kmeYiLOGQB3LItXxdV0P4m3Jw0VCoQx6Edq0fjCGut+ex4nWE'
    b'no7UdkKW6rhOa9vN6zutlXsw07Tl8gP6vSN+q55cDDKske4SDeFsuFp+VqRj51pgUAhkkM7TJQhyBU4IlJlqFHokBtliGTcXQmqB'
    b'JvwmVFcUhEC1VjeiMy1UHJFHxacvbnSCIPGpTop4dLxKfiWij5mLChnNkY720IIYRLHiwpH+jy45zud17QkOqRORW8rH7xYoUlio'
    b'P91qlkJgoZ0CZmXzDqdJ7IggIiVH0DUb6eK41soRfO3roiHKSpLQINjSLl2RQaqS0oUDrYRNgCFa5FzsI9fu+auFwfet9+ry6nTl'
    b'YCCq46voBsnulqQk3pmnrY0Hp63En6exNVajnVXW1br84G9ZfhgyWb0pz6XBp6vubBz3KLj4EO+yrQ4MuR2q25CvR+MiNahLMC5o'
    b'Gl9/7la3p3zgjMlpMhQrwcE7EP2T8dHqJm636MqmkxhGW1YjMpizNLqqyyvxtkEyTW/MV1HRPjYJoHw0FzYo5mj1+9rUW2R+TdJk'
    b'W6URv0MYsqHJ2gHT0gTEvBWYEgJcAAbcE9StQM5XXA5Uz7qNs8Re4PJoTN14ThIlwjhlm+X6TWOV4uI+lGXw3a4zXa9LATMconEu'
    b'AD1hX79+++pP37989z+id6+/e/nTm7+8jl798N2fv3/7nj1honZ8XoK3b3ysbBw8YYhJa6tfb0RNAadO2+hoQ3wPq1XLlmdrHh8f'
    b'eas/DVR/8dRb/UWg+tHxC/9ojkPDeX6sGyng3GU97nc9Pp7PJzPwth47wA2UoUkGrvBXOjyfzTtfHkwQaARLWELclmvMaCNeybTu'
    b'KEq1OsKSRA3y+fFktskKSPZ13qiR0hphDm6IWKbRhb4LoCIEoLHNHzZpvU41Sq1TSEMJyaFpX+zlQ+yNgRjYKYE4aj59heQ2+xO5'
    b'KaEizxHJ/fy5/XBop0tYAe0VUUMkT8sln2H62IlXc/HPMMOHVoGhGsKwTrRaahvHYm9Ot55KgW6N5zKze621x9JVK/XYu9K2EWoy'
    b'mxnrJ+T+KyqPRhqzoTTj8gN1HzflSgkA2tFO6FFj1M7UPF1BSKyFc24rKkCpGKroKFDdZHW6BA3QYgSWknC/46W2cjJwWKmFytYF'
    b'Gr1Lcmu0jcTPF6+udFNuoNyjK2UH/hbGuRWKAmIP4WnPEJ7ecQhPhw/hRc8QXtxxCP52/oU47luJ47suxXHnKJIkWseVGkl4FPrZ'
    b'ucdIgg30g1PIjXHbxssLndMbyo3f+pzUrFmFhW2/2bXdNIPIcVmLqku5we9mdKqfbtqwpAYMXw0bsAYbg6mybpSOGWTQAFsP+ZZw'
    b'rmEMVElGxme3gUgDYVTXzKY1XJFaCF3G5ZhIGS888dq4Bmuqow33wlPVnnqqPXWrvfBUe+FWIxW/3euxW/H4mafi8TPP+Hw9PzW7'
    b'1ixhSLulnMkloGWZu9pBeUQZeDRlGtJoj7lCIqrlFRrCw1jfiE6lsSAnEZX9U52J+jhN1+Ie2YfLPVUyexv/hA1maZFwsnT69xmT'
    b'JQPSRgcfILlk9REuiRyy8oSCX9si+xlypt8jNLEynbYFJNNhSD3HJIgDvWvNSJ+bDth5cyGC6RPxKUnzNh4DgS74VbLjFcWewokD'
    b'+LZHre1SsF+7zW1dBXU8kMmrR2unbRKYIlnD9ta1iReaih/dmimhdzJc5iRZSd4gzruwAuuBLwyP2TtMjsEwsh88G0BgDx6rGmTb'
    b'rFizpmRVXCRxw5IyJV1fk+Vp0UKo/DoVk38sVILRZ9E1O9R+0cNwnsaXKQY2W8ZFWWD8V5kCCDbcLCTbOvwoIN4KhJLoPjZQOmU+'
    b'gZxdlFeLEcjro4kKovY0Ociygw0wVSOWmojFll5C2gge3k3c4e14auI7D6imK8ZyuPsTkDhP6/aB9GIEyzQjEVdlkFVSHo3f7p27'
    b'yBqWJNlKAycd+CjZqular6p9PNd61cfHdq0nvAxxKtRqhqTbgQ6EOqS93en3cywa/eu//iume3z/A/znj999I3SUK8CWsHbQMcht'
    b'HWwB5m7HqzQbUUDsFRHKBI+61G6pKU5lS3EPxhqWbIrf/NXhqvQ88dXXFZ3PJ+HWkMGwp7kemUyoNp/PPW2EOvK5qTJ1Vayhhray'
    b'1RmxUIY85xpXe2WV7hXG4I9Y6wUodbhhiAFtrqJCcXxiAx7u/ueff/Z6vyFFS/ritXzWSlRkUxt87TDmpUZqfD///LOfNCUcmyh/'
    b'/vnn0xGUahSmKvtpy2gj6MrbSKcoE3c///wzx9y2Kf2YAyYgMcdr+TBHRTbm4GsH5qiRGt22Kf2Yk3BszG2b8nQEpYQ5PDURE6qF'
    b'H31Gw+N5X8swDrdNyXG4zhM/DoGDShzyWj4cUpGNQ/jagUNqpEa3zhM/DiUcG4frPDkdQamNQ9XCj0MTEes84Yi4zK57nYAvs2u/'
    b'4y8UKJNJQMtl5uDkMruO3GASNE+obs2QqiNsHpldzvEyu/ZWo9ka6ADASbZahVFAADgWknVzNO/FA9byY4KKTFzgNxsbyboJYoMa'
    b'WPigBrwH31SpVfdkCQif7MUuKuN+12+q5p8uLzPnSx/tCV/sgvPlDawJYwPRhU0C9DVQ14Mc3kU3dhCKoITrXT8dYPYjHxVc72wa'
    b'uN45FHAdxghUt9cfqyNsZ9ND9SHbnWDwGfKRcflw4MO5IUY/Yd/Bi8zrv7x++1P08rvX734yXmc895HzNMdIF9ARfqPpL8tiGbdj'
    b'GsqUxdcZqC/ceADYJBRpXCsMRRoXXeJ/T3/VWsykciYZ6+9VZ7MVGJCPFc5u9ENfuM6J37ezrCF7ED4cjjntckR9cyA5idhCfjDK'
    b'uFRxIL6a8qwvSUAHZK6HI9IGhTwuiCDqMhfJPtJVvM1b7sYh2/liU2i0wl8GhAqnrCMOh5CAtrkS9mRWp7Sm+oKpkVVlg4Stjeoq'
    b'KxLQYGUFDAlsu5tlnKdqlMdghucfIk89ac/XTLagzWVsh5MfAwQxhgX9x/AqYIc0nAlZZWPojQWaWqP6foE5E+T0inT9d53ewUec'
    b'H274OkO7XxGCXz2NKIU4/JPLbB/wcigSEYuj2QsrOJbZ2uL3e0JwDxgvgOd9AIaMwgYiqcHc3d62nwcHYB8J3uZfaM21J21tE/KH'
    b'aH3thy15s2vadJMtH3zZe3HeB+DZQyzaswGLBpe5QaumGjt8unfZ7rDqv/94q34V13stuH3j23ObeuXePTfKHov+4uHwfpdl/4jr'
    b'lqSrtGiySzMj83z27Dn7zNzPsvAJm8+eyuKruDZKjufsMw0/9q00MD8+/EFDXtflFSq/+6jNOAddjRgZ7E8HNwGdl6+NmuwADhDe'
    b'wXfjAIqU9iDnMJAhfDjcesCmPp4dfxxihtsEXF+LagY5BTGxJcKcgFhOz0GAU8PNyGlK8ZHkoMbmiQbxj4xNA2k8A3WISv0V4OFE'
    b'uw+BkBS1F/CCUuaJbnQgGtGVSTMdozHrxmK9swAO/RXEm3j2hRqV2v77DOsqrqMyyyPwrHuIoaGU2DsA/6B1ZOtJRaFtuVo9xPA4'
    b'w3EHSAW+IeKMvhyOUQ6pTikAUfeg1e018ticP/IHpdUv605IWv3yZW7ukT18GXVWTDNcX1Kv0UZ8DbczyMtoexXX4WaSLMw28nO4'
    b'pYV9ozmVhdvqygwtgtaYLxkPv6pzN5MFKchkXjHpeTWU667He9VfZ514ryIBn2homKs7M/lHNFYPKZYe0GAbEvEFVrXXECqo2wIn'
    b'glHAvkhon/psBey3VaKk/5sw9XeynucKtG5TAU+lQLeGtjG8x13rea2033r+ITSye1jH0/TvbR2vT/F+1vH+hfCaD3E2SCmhHVzU'
    b'KbjZ7Wmso/KRmuY5BIxHevHY5Kgkaw/KFTpSXt+MsO7ohEFg7NsBqa811AHcR0bg/z6ixrgDBzzDkcr0oFkJG9JJIHu7ubxdidyt'
    b'mt6c7iEb79HJEPNvPQd9SBiAaeiJCQIVMSVgAKAhcgXyHfirhyA6Qlk/VKtJCLJXbOuH7mkW6sGV8PrB221CsAMyYH8H3oaiF5Lp'
    b'OjYi3wwDNqC++Yh1CUNFssEjywLMFuvJYjxlVZ2usmsjD2nA4zaQFnl/F9u7+MWuRjc00tvBvrFWkz7/2OGOqxrgoPNq0NDJSaJE'
    b'PF0YTKJV6cNYhPL177MINXoOWIOiCeVqPds2gqws+1ct1jka71sLq05iai0lEXoXf/f6j2++l157mhkkGgZrFxo1pUACC45dbHgH'
    b'E0mwfxzTmH589+bVax5I5v1MGOFP9rCXBOkbfIZFAEkQgX2wHWN4npGoJwolbmmMi9G13SntsOFBhGaYUMFnDmvZ4GGS6X8W459O'
    b'u59fohdP6Znbedy8zK6nTLABux1XnHKGI02FBKP5r2IrpBCIvwO1TGRoxkRhdPyTWxMNNiTiONFtiMJI+acxItLI4nrnraGdxpaF'
    b'UQdN6CZGm+Pe6W+O/bPfHFuT3xzbc0fom2PDTAjCNMSbKk/Ho+/fjyYzuDePJ9yIB1N6LzRmAJKN9GjYHMNjTBo3cFSuI9RYNewr'
    b'ZsUvlr1eZKvWcorwgtAij22Og4u1ObbXCisDIqJduQN4fCk2x2ZMj9BKYHu+EColZO+CGNkjPQujlfMFqtPLtG4grkxV9oLXK/s7'
    b'MGrwLtp13AsZEl16AUKBoqUxGr3JSRBRYRAvLNF7t8vadcw/KZLIs5+Da1olM8phcHomVMAjoUd68ey0aM6snHW+oZnUJ7ujP6Qt'
    b'Ff9JtmzbIiuLsQaIKMv0XaEW+npCYlOisFDCU5M41I+JdxzO1Fzc3nlyBqiu6ekVB0zQIk/958BJSiK589wAQteU2nU8YCa0Hdp1'
    b'PHDcvHDA0INJecUAi7SN8uznbZZk7U4O1Q1kZsYV4NB5BkmDKIf4YR10gHOIYEig4KHAxXLsA9P8ZfJtgs0Z97LKehnfssr8jA8K'
    b'zEN0WWX2ClMPUPBA52iTl1eDTlKtZ89ZGgCj7YlllQVZL0C16JyqI1bgRCWNQZWFDlO9+tNNFBcUWrSoZhUmVxvD8A+14T+dANbQ'
    b'33Y8lwaYU/ZMj1blLjf1I5a7rNNo0JrzioGFF6XW6vPPDgmoXmWV35wYfGO4G1nw5mHaEPBtAlENFQoVqYhWg4QvDRZf2mrAqlah'
    b'Ba2ctazcZaQeqr/D4mk932nJqo7VqtyFouqIFbk81dCVocbCha4AHXTvulA1/9LwMnN16KPjWSd648X9y3TPdXE6vNPqUOPgAnHY'
    b'tpOfaCQwpN036UNH1acbvo5adbp3Pw269AkgfGWb+GLTu65QKZDKEkrMNYVP9oryXrDoo6+m0dmdVhKaBtcR4VqryBsQPjC0PNxd'
    b'KGh4fLEJrAVvJe+eItWtWI9lUURaAtzgEyddh0Q9xwJiDdF4VbFmWkLF4RzCqqxDsCT4671SPqsQkXb24NU6iPjV2kY7Vh6UyHq1'
    b'1lKu61W7RGZztbCzbp+wfzTFPzbZz3UMm4Rcx7TCkOuY6BL/e/qr1iLoOobtHrNv4izfMXhbTilQDFuWGHeDQawbdpWmH/LdITeQ'
    b'4v3wXdzM2Ku4rncQXIVD4w/w1fY8zxoIqkEUyESAmaZkyoKD5XGRNKwsMDpLkV5BU+yBQ2uKuGou0ISnadM4YeWKxaxOl2nRsraO'
    b'4U2SJfGOgYEtFL6N3zYUzmUJA5Nx3IQ5ilw0U2+lpwzih7aRRUiTtayqXPTWvopTX/tknDDud3Wc6Ia2BkfTCqy7p25hal8jtTJx'
    b'C9Q+uddgoxdrw1IZt5eAYLNFG/lxrMXH9FQQ8S+JQo34l2A1EYSs6VWRxMM1pd6hq44hYP5e2GyL3QBnLSvPm7S+xIQoDYvrFJ67'
    b'NmWR7zTqxsybFFuorOu0qcoCaJID45uKnnXZS/bjm58O4PkeUmQ0wCHZJsbNU1Pgo/R6mW8TilXUxJv0IIlJ8/1YHwz69tdpG2e0'
    b'b6o6g3R35o4TOxPHi/Auyppi3j8W2/dgHVdslaV5gvuTxS3blE3LVmDIjJygKfnOvG41DiHDMXFw5+my3KSsqbZ1Vm6bfAfbcMqu'
    b'LrI8ZTFbp8U2K9J8B3Gy8pSt4Kht2izP2SrOcuA3FGidx2GCFZByAi2du33Vy5tGtOqxzfqoHkq0Av31yfnsbWG8zrjf7TbmZrHm'
    b'Zc+IdoIIrAd/gtliCBcYMF/UMraS1rO2n9zOQ/vJrenuJ08dYz89l9vpT7OjuSTNhubDkjLP4/qADjtjl2UFi/mJw87jdnkxY29a'
    b'mtJjlpTLLTycp0D92DW4pELjHCJ7saaKC6JdTqpN2jQAdgp0zDdMLE6WtIrx8nFebosEdnKel1dgFMjqGHYkay/igl2l8Ye0gFMG'
    b'eOuOT4BkdSLXi6N5gFi1Vyx6R5MPVgZdGAAGUUWgy31pwu44RBF2PZcenBoGNRwp7vqXN/92AP68Cfs2jevf/RGl7qour3c4RbJt'
    b'wwBtVVpnZdKgDALmOq/evmVJ3NLyRbCn6/jKETdp1ihxKgbhCxoLJsOqhoMwK30EJD0SXWpBVhTCsHR5se4bkOIQXdpYJVpGTbWL'
    b'jjZdYKFGOPSxD+ZqHRHKbZ33fPYcXOXGR3PIfHw8A4+6sZz4ATuaT7jbE+Tpmls6Y3S1wybPoTn8JdAytNUTBnZQn4lpB5oFPsOS'
    b'OlKLs7LmlRVwUcSFJGjPlYaSyJqDBnqglrO42NnBJOUOwlRNvCK+XHquS3I19MoqHZYZQUHtzR5g8ra0F0Zc0BiuMzq68tzsguPw'
    b'xRnVwpqYM+rp0gzPaou+Q6YiG8itJx98AvMxnxtDsxEWBoHpdHRrzckR2vtnZTQZOC/3nfFOM+vp2pqbuHT0TwlqDpyJfF680wT8'
    b'HVnjdm9G/TMw2wyci+cl8k6z6utcD69ixIgBWZXpZ4gWIcaY78TpU3gHE69Wr70qPgx+PRBftU580WHCUM3FuRk1m4v7jp1A+Mau'
    b'Ad977B6oOuLpc/SLzw7Q088UcoOSpKJ9DogqysuPehSqKl1zJAfxdNggnvoH8fT+gxCL3DUKmxC0kVhF90YJX7ZOnFhLq+PFLLrv'
    b'aOCe0EMl+lVCG4j2+d6DwDtw3zBsu0x9LFbZfQfEb9hdwzFNJ7WxGAUPNBA+swHj8ePHKbzvuCDQQc96iVgI1lC0z/ceRLHuHQR8'
    b'8wxCfb7vIJZVWveNAut4hqF/v/ceOo97d9B57N3I6vN9B8G13DQI3rlXEjHNOF0hRFlp6X3gcI2m9x0wqvDUcaybz4s7O/1+iI4G'
    b'7GLLDh+N9eVIHm77wuGBDj0hSVFWEB4/AaWGXe/eBETdw6MGPHes4yokzfLct/z1Y0imHq2ZeF0JPQvy8p5Nzc0tpuzFXOxn+nRv'
    b'nqK9AHWPwTDL0Qaif78/hxPvTr34EJZhJkr41/uOg6915yCkDYwagfj0EN1DDqm+7iXdmkMQn+9/6KnHvZ6jT7czUYMxvj/QaAZw'
    b'NteWxRmSKrvvsFyNSNfQwvoT7ZQMVrrvWH06jq7RdulEtPF2VLvviDWlRtdAPboPbXxu6X2H5dVKdA2wU42hDbWr3v0p1VJFdhOq'
    b'R29p0Khbfm9RAQwDMHQZGCxpkaH8gp1lGeU9lkEFD3FUIYpeZ2Az0RdKGgZg/5uTUJUMn50hdag1zjbVNgfnb6nr7gu1Nw5Q3yGG'
    b'q+2YpBlYaXzgZwd7gzH26L6tfexzXxjyKrBHQy16irZSIhpeD6E4i5jUcVbss4QHD7SGD7OE91rBg4dYwoPffA1Xa1ov/tqqVurO'
    b'j0F7vtc9BBvRepFB+PagwvHz+QxeNHVcALc8fr4vBTgny2+8FR1E7LUbxwYxHLDnMP/98fB3QoOOB/zPXWgB1Q/mfHQ9glkidJbe'
    b'r/4mB+KNwPosFebmd6ErNr/OZ1/Ag7p3hwaYsbtNB2LcxCpY3YjwHMORKp4kzFkEpiz1GxaGutHqWbeDEPJeDECeJY48CPqyYpWj'
    b'GVQEZjUYOWQ4DoX615yM0MeaX6WC1J45hlAWakuL0uSDwB1mpvC2N23wsM/i3LNH/HuwFvELCdZqz2efQ12vJOBUfQFV9eN+6rOT'
    b'8Zzog0jswIfMfiJ2t8kdSKtO4+UyzdOafg5fCKn8smjJUIzZdKbUVF4E3ouotlXT1mm8iZZl095ly0jtlRX+WmiVHL4AQ/bvs/ns'
    b'GRSGN9bcu7GGb6D4vKyjply1aIu4D18wlFM2dzBURRa1qVuml00ESXXwpJo2XguyHD6hgRRtjnkQydjTRH7RvQBeEull53fAFY/o'
    b'pjNSPbbbHogL8WIvwrwn+l2EjT3OS/h3MJ89f0gRpkOe4AeMtAFwBvKFd02HUJ04c+5AfXAGPd+D/LoJiW5ywifD5/7kz7NuXMR8'
    b'Voh6MF4sfsx+vAC77C/i2XOVw/jo8wlEsMzbg7hIDpptA35dkO95mcebCtx/yLgagXI4RHMMZzpjP12kDXhNkL4MfDHSDI20/0PZ'
    b'gk7+AyyJz+PzLM/a3UHT7nLhlFTWcnuAk9AvBwi2ARPvFhwjtnmCobVh0nW5XYOj0+nB0yl78vSMrLwfs1c41rZkpwcvpuzFGfy5'
    b'BBN1Fhc7VqdNlmzjHKKbXR1sK7aqy42jNuSgxlcX2fKCLImv2C8HMIUqTdj5FnzgYTDkHQHh1SCkX1a0Jcvjeg2W7esia7dJKozi'
    b'L7PYmNsGRtOm9aaZzBj76SJroJ/lRRpXbHyZLsG+ukkTTE/MQaRgpl1gHnl0ZMnjpgFQ59s1Yaiqy2S7TBP2H15CZAsO6OA4PXr2'
    b'H7Cex/PjZwfzFwfzI0JfRET36ruX3/8Yff/m7dT68vLf2IIdvIAr2wseiQDolQeWW5b5IMI1q/dSr6o+JPyH02ZAzA8Zb+G0qGZZ'
    b'sZqyA/rjzE2AJdtod1gXbXShtZFnB+9QRwd3AYRAfBDQWvOEVHXEazs4BUv/UK7+yeqmRYQuMHasgdPTuXJAVhX/m9mNZSSn9VXo'
    b'Tpo3EsCJ0XzKRjiekfOZB+a1vn7jfr2Vg9S/9vA4gbwmrVvgLmY3YfdMj+GEq3gIuf16KgWIjHoc6qRKcV5B3gL3DPK1EuGkZZwz'
    b'Uokg1x1BQvVlXU47XGW50yuxbD18vw7oHzJ0fzcbuXcwejNSvCD6rkirtls5Le4/xPD32zRou4T1BrDfICfw7Wy+hzs8IvxMzAU+'
    b'nJvc6nxUgje86rXanjD5Rg9OmPy/Uw6BYVH0iRMN8pw/C6PkbqH3dbTdL/S+n5GGQu8/Zu+BQ7KnyUGWHWyyQgmwx/PJCWtQeALK'
    b'ggUua/bEin+LzogxjlIyvkeP2aa8TBOQFuuj+XwuS2bVbvbokd1vZnWqesCbWJzEVUtXDgGHPXn0WFZLdkUMYdHzNAYB+yKrtHoU'
    b'3GITF9s4jzZl3EZwFtRZwoHEVZXvRDmF/MUaebyD1qIPyBYkNAp1CvchiGTe1mmxbi+M0SzrrMmaiCNulbV74eIygIqmBbXFehed'
    b'59u0qjPw7+YXA73zzTZvsyTbQKj1sojzqMrA65RE1mbwSJ6dH4TWhPNxOEZXZZ6BVFi0NXhi6uNQkfvP07gFoXlVLreNwKw9kCZb'
    b'F3G+H0Y2WZHWl1mRRZsSHGS3mxB0Z5qYaxfXnUZF7zu89ThZ2SHbnXO842BOVvqZnJyOCDh1dF4WW0g/Aem/5maFSlZqyzbmDizB'
    b'FL4J+IBQhALMhGfCAmfTaFMm6WAwVDtyIGrhrnuWFGBBQgZxgoro5T3NtKC5HlTBm5snTCHlAYAeDFhyP5o3g89CRsAJT9/sGV1Q'
    b'veKPHqj++lsJypk2brfg0pzwODDbIom0EhKm+ZvuaCSE18RMTAUJAmRAe/ghO1kCEdYbiovQu75pTodIpDcT8S1wrYcYv8AcYorg'
    b'Hg3u31gHczAhePrAFH6HjJCfFg8xOA+ou48LvOmjoozaFlyaxwaF4LWxxRD5VGOEueuMOXxJFkpqnmUCGrj0PjAxAeHT5/7OXmid'
    b'NaCk2reroppt4utss92MQ8s8FTpUD6onOIpjbRTEDJZxRXKcsoZA9YJ392gZIAwI6HFsoRA4jM1TqISzoWVciRGmSQiots6DAEL9'
    b'ECwD7eiolxXjYRCn7MjAXXI60jnqktuyq/6Eukag09bRBM8wh5sG+PfAEKwwg02MecoDXX6lRq1Gh/gSbeV5Zo/VRK+oftY/yUDB'
    b'gbO+m6xp8ADRKL5KiziHYNWfAVaRV7hPaAfsvvsFmdJURW4wjyQxgz1FCvZkkOCgo8Uni9xZmrHygy0vtsWHNBlj8g6eCORlsTub'
    b'sib7JT0BdTFKZW/gOnKep6eyxhnJGE2bAvvYxNcYoQ9awV7hKr+yZhkqwjFQ5XzKIG8t9jWZYlPNnXYHwYMYFp5m7IRl7AlWOeND'
    b'Lcp6g5HKeHKQpLwqeMhDuJYng5Q8oM0BJTYsKqjyk30T/Rix97IVyxoIJwa30DFkreS3B5REvodbAwZFRw0508pnBd55IPDhkepb'
    b'q8AWRvU1mCXgLYnfjQ9UgqBQoDdZFArzRhOCajzs30V5tRjFeT4KpPhJr1u4k0YYTYevAkc+X4vUWoUp2zW7TVdWJlgQ2dhYGfl1'
    b'+BLxkH7ammhQAkvjwO2jMwlRRN/cntvhAoWjDwbgcYeApfllDhlVQF05vp7gVrnGMGdl7lnvOQ+xl1/mR8NbHfFWba2hL1vhokAr'
    b'gGbF3cTJaEO+bsZQW0QbhB18mebwB+qo6Bdk2dO1amYX87t1MQ90kV4v06plr/E/WVloEUpDKzFsZZvt+cRQP/NMYZBriVcJ6ZlJ'
    b'w4F0PmV4T4Tr7g84vjg3UytNITghljv86rwsc3Xn7RkuQQkrqfmkAXGYC4IPSw86hGwJ8yhRmUgCgfaxqPQnrSVgIzFiUJ7yFlOW'
    b'nPGFI3efvbtJzC7oj9Nf6b9Dok428WXq5JeackDG+gMq+AJLXO5WItcUMLVxs9ucQ/gqOgmbtj6bss8+Ax3hujlhL4sdrpNaf2Nl'
    b'T4wQuhySvR43t+6W1Djggu1WM/HbFGs4RPN1P962ZRQnf9s2LT3TWMV482pw+1i2SXW5BrsBXysxY/W1b+uZkyu3rb5J7MxivBYw'
    b'L84lHGTRVh5y4EyhsWEJjtjfnvvSO0DaO2Cd0AQD+27PxZqBZMKHMYEr2BFSLf9yOj8T7xUwN2uYe5wYew+T926M1jmYtxWc+lFZ'
    b'pELXamWGG/pepvExiyGJbd2Zzw2Z/oK1JWwrGvxYL0+LJEp4ukSZ/nS2bZdFeTWezCQexyAm8zpo1z1O4h3EupVQmrYG+kB4s6at'
    b'VyjyjD7594NPNgefJFyCMTYZhHWN6nQF+enx6lLmw5kVfh19k11mSVokjXy9EpVEdBh9gTXgQqgxYZa1MSgrzjwGrYMb7+gGrkNE'
    b'WiJj6y6N6+Z2p5JKS0VpgLGdwtqcTTnYBf1nKoMeLkZHyWiCejU6i81TtOvJDHixu6pjSxoVM+cSKdwXJsaKGzDbMol30bZdDqEV'
    b'+8FSDOirBRsrQAdegvKEW9MPC/1708Y1n6jooYNItfHIhl8Jih3eadeSOkD4GjvfcQALMQzvdnEbpUWy4DvNLTTIxiweQkTiwb9L'
    b'ylInuRI1Bp5C9xR5+GVnQMLN/diqLlUgd1VxH3kFkOxbPBeRuYiveM0EmT5LOLYEb+UiEIS+lQkA4ky8uEH+XWkM8Jj9CAbrBSTN'
    b'jJcfYCSsKrOmBOOrE7bM07hmoPKHK3yiVQKEgdRF4X+X27pOizYHM7U8vYwLKenM9KHcaNPAT9mKfkBALT66ya1+9kKtCfsKSGvM'
    b'bbqBSeB1oJBN9A2bl+vxanT615fv3p6xr+V4s0abxvhGwr49xL9l55MZe7ltywOcOURllVOe6fHjaT4wbE19CyKni+gp1ubXwoKS'
    b'AATWsxUHCLTgVzuczp/hKIfR4EIzpDuEgIMHoJOT6a0ENZaDXmgznbDZTEwCrgnwFR6difaM6ezPaeUhrpo+yGFtHIW0U9ptlae0'
    b'k/D/QhcqOMvPeM5aALWuy21lbld9V94Bti62xnkOdgMR6CXz1B3qkFFKARiJAJZV0XVY1FIUeAH28kgbCzaYyylVm09OU8ANsUks'
    b'jRCZVM/7ikR8s2N6QQkFMw4CfPdM1AlCJHAYt6RS0k4FBco1gIRX9KywztSPIbDcX+zwDvWjyhzeHj1bBzJ9CJ1ytxDBTs8me65U'
    b'+DD37DUdthcq6U5SCKmbFXQlq9MGBl5+OEH6tXQ1sjGVWseyTrHlB9LiWuRrjlcw21mcJPLmgzXw0R5NvPk+Wqdt3LY1Ge2Ndqso'
    b'LUDBzu+6QuYbTVGa4QijMjjZNJW7A8iEgNVHU/bi2YQU8wpH9bbgoiQE6L8Tz/VpRxz8YT5M6MHAFQlrDp4lopAzwJkGTelKbhEH'
    b'sE8uI0Y+giATfLtf+FfCc5hScNlQI/VmAVev3QpCqNV6KlRru/VewGUeJk4UfkhyaM49QP93XqfxB28pbMhZk6dpNZ7Pnrns0LMr'
    b'lJitaNq3TEogwmssEDKonfnzEWB5qpGnNT8uIcLRh0cP4liwh2hK+MbW6ulQz0/fq0q62+IR+I4bltC4SSJ3UQr26lYGof616lon'
    b'napD/FOiKzAn0BpQ3qP+u5hBd/veyLDUi5ThPFP8ewwbMmfA7sHIjDj+AXobiPVh55TbRAq9ICjHjL8Rk7BM1xDv7PbepQ+ygbTF'
    b'5vSIPzgj1piwLu9IRU2n9sfW3yi1Kh7TuGMw9wpcvMoa9Oe+8x3fXMe6UGIdDVNDhYBgdfVAaBQOuRgEbMvRjx5orfZZIzicxP3I'
    b'uPJF6IwHYhfeuqgKBKjQ7qR4GVP9wgW7BGG4Bs1svE4PwRbmAPNWMMjU0+5OWFJSRsu03sQF3aPVTRs918pCI2HgLmo0X5FbKOwo'
    b'c1hfsefWIxtcJl3eIC7Lf8rWF2wHeIIcJQBjW2OukqxkSdqmS8iLMr5RXZ/Mjj65nYo7KO9W3kInM2YqIuHf6P2HrKqMezVfVNjd'
    b'8WWZJUr/MDPbd6kb8UL+nwu5buZB030xtzEkEfIygbcXe3o2hhoYuaElIFUR2UJ/aMH+BVMmEIkFXgsDD+FohAUNTkfEeTdZsxyd'
    b'sUOU6XToM+6oMzJypM4wz1qjJ5DwPZQri/b/n713W27jyBYF3/0VeaDZNmCBIEGKssxuOoaWKLeiZcqbpN3t4WaUCqgEUS2gqlRV'
    b'4EVqdZyHifmAiTMxTxMxb/MfM3+yn89HTKy18l6ZhQJF9+4dpxlhi6zMXHlbuXLluta4QuCwYAKHv2mbkiiuVU5680WowZYc3qfC'
    b'bajoKJ37zOHQkuNGd17yIfOqWzWjet/FT2am41Th+EvRUGccuCITRt9Vs+jhgmWNGBJdwihum0J+lR51STiZgiFTo6yaxyXYAK1q'
    b'MH/AhHZ2yPtlsUghPtKaetZ2w+PzbjY6xzH3fbodQ+uRzYBoguHJLAf+3eDPILXSIdYg810yuXoeF4a0bfkOeiMbsOt4gRplaGeK'
    b'NlBS63gaNRYLtGe6K1nQwzdFzxTv+VbTbqyqPA9C8a4nkPyIpqKBUc03uqJ06lu7PV5wosVZCGr4MNJKG8soNbiqhjyRB/Ly1CXW'
    b'CT0AWGbOQmsvegfO5ph5ARuL3zvw7IiZyLCxMmoQzSKjXXhlVftwFQOOQYoOAuLShq0VNf9kqxUscvBZmgTwr7yNMn6DxnrskO3v'
    b'7ASuGCkwbL2vhO0SfLiwSG/Twoz4bUREo2Io7DJl2oymaHXWce384jPxYpKaXBqrb8TfHRq9XqrU8DhsUsHKSHCuxdA8xvDZICfH'
    b'btT9dDmqc1j7/mCgM8iCgNKAp6XraE96tYKczJNVcsVh6k2ZjbUVYjcjjB6/ynoQAXRnR5zndMbyasSz67TMM1r5059Pdp99E33/'
    b'5ueTF9Grk59+Pj+L3py8/hVuTsjSW5dp0UfxSW9seFD7RkYW+Hw2A3v9a64LgOndGaK1NIxeDHEwbEIR4+yo/IBVvrw4cHtU2eVs'
    b'uTi+ZJSMX9mXDgk+R0PYuAbDKLQKwRfL2HlsAgyVDNhzMTsPY9C8sX9hT3Zg/RwW23nbWc4JcSLMpTReoRTLZOxNVMVkhUnAwTZO'
    b'knUnsVGlPVaiewpQku8Mh8q9A+pOHDoPSpImw8IMPw1h9pdDRo6W5IpLtoDB0xwnZFL2G4/Ufl7RKCzvVQPekGVxVORVSl6nGJ/A'
    b'CfHQdPlVDHHD3Ve1Mf2Tob1jiOkoLEMUf0ij16EN2jBBaZaMdT/4rdZb8CTYwHIwjJMyWlX2Jdb3Ovt73AxDt2vg1uz1eidS68OO'
    b'XpyqTLwxhnD5+ewFOvNBrBRdMiLpztviFgICIUvxFrhYVOIj3crLJM3i8o79fCYqDDFoC/SAlA4DowDoSQoKPYQHnUEFUg5jTm0F'
    b'B29OAYpCxpwdP5dDm8XTuhqx87MfYRQyxfY0zvIMU2RKGQC48BwYXXzNzuP0BsLByG5EBxS+iCdizgJcwSZ37G/7tyP2c8XV+/mr'
    b'yrNKz+OCxRQlBsPlxNl0DnmDRSgZ3GcsJSkOMMFHL063SEgB04GLJbfSfN5+LQaHVF5unkRrmXXcMMeS4R6UOVZvlaUU1K/KV4CH'
    b'KkqBCgxBpwDqigMaqNJ494rytlgTgNbaV8cdy6XptQgXO5BKSERb9XvQ8mae1hx4kx6c6IoLy06WxWYAD0E2UQcl+6PMk03JgYjc'
    b'kFwIFsXnnyQec1Qe4v0UhKi4lRy2dEI1oKtF0PYwQmxJ/khyvEO1+JfSd8Fy6RytsvT9igNHKZk18aamVKUBJlyJFI0hKPb6EJgg'
    b'EBAZhahQU8tK8gGNS9YrSWIJVWrgCEijlDAKaAy2xWNDg15l8XWcLkBF+DuRfxitRBTOG7THuCbsjYSbxJMXWAcEscO8qSvI/mrL'
    b'Z+wy5/HnlHoefE6N4APNqbf2QWfEMzM5n2ljD7BUZlF2M9nilwu1bBqURDtKEajFV0Jedp8bXcYXsfkKGWykKV91HuFIAqwrflW5'
    b'tnm+LRItWzcutHmi7dpt1UKggT/OhvEsEfJAe7s7zG39LLqN1eyL7OpB5xDRjWOilf7ViQYiA0ijMq2P4x0y4PvU/qOjFcQxAREy'
    b'VIarlEJWUbbvpjDUIpvDwIqoh5MbGyUQvsfoVj6K/JFeqCLul02HDQiX5k1G31uovn2LtFcPXCqykX8pgn34q7f2geY32HrNSEFF'
    b'g77aa8YG1az1QvshaBLw4knadla0DGxvl9hAoZot7yBnZay3j4nALkjvum5CK+VYxYmE2axZ7e016Ojdabeb0YTXN5xn4F09xnTh'
    b'I2cPqWZlLIl6nMnpDAx4sP7pVEqKpCyJYLRwYq3kSfBTijlaxkVfgBQvKk+i+yBzFth9wXx7wLSPLQBOhgpCtldxwF/CUEdZXgNv'
    b'x74UncoP6jSI3hxu3UPq9CQlNw1qk+I2AvyvxLSFUodonBqWosIUGze+ccovIX43Dc8paAdnjQQmfjfDRy2hLj501ONFhs+FZvBc'
    b'WjdVp7YTnK3BTfvq27uroa9t29hncR+K6ATu+8EB15U8i5uT8AyljSCa9Cy2OgyZfBUQ+lTxslhwfVrjCuIl9cv4JqoP15D5bTbm'
    b'490h8YdG9SABgupmt1F9C7QGCOQIYn/o9Z31PpYjGvOng4/liDDrYLQ3+3TL/qeP5QgHeDDanX063/oOPohB0CetSAemvkTLD+xx'
    b'NOdx0n86AGuPEo38qn4juqOgsKgah2cIvD/EU0RavmJshAO17ocf5W/Cvt58Hn3CkLJKja4f/ojcI/ZRL8YnXxC1w4f4+UIGEt4d'
    b'jQ/0YNIsWVV1ece2wa9uS/255HWcxHUspE4PNYhXJy9+Pjs//TX68fj86MXR+ZGMeaeeYvZrC/TOFOzM+CAH6fkUJWlVNNpG77i3'
    b'svHZFFN+IWMtoIZI1ZZL8vBmDY0uHsS2IbjWHmMGtLN/UFOGNb2rt3awnj+Atraot4XxyYxib+oAPhSpJ5/8hU9r+1DNTOuJzbb3'
    b'M00o1mx0dzsKZQzmwOtkU9Hr9V4ClA2oAGxXLIwRhQ5LyHYN6eZb0Mi/ZUV8h1aK/BZCbeNnAvd2qH9/kVaF+fcf+d1bOopv6cy+'
    b'HaKMXfwFxTiIZV7VICvm71dpnfJqxNifwD+ogCB8DCwn8xnIS5esorjnIDvlKPYGOa8Mcr6qOElV4xu9CnV8m2f5kjxSTSNMJSjO'
    b'47LiJTs7+uF4+4dXz8/YZDUFcdMSQoG//fVlpLD5/E0EFaIfTt/8/NPbAbuZc3Jw4Yktki35NC+TA2ejwKa3iwmCJo8HiIR2kSKU'
    b'bYVEMn01DOLZCsBX4RGKvk39NuvXH7ayGITcP58/H7AqR4NWiuAPKtRpXG/D8wl0lncgWjeAySfa0ycUgQu2vUzJ8DVjr87eAMLD'
    b'X3NeclaU/DrNVxU46sWriidCbyBgAQCwlsXoYgxEpey6YmqgAxbPal6KIZF6ISb19uJui1zYDXDaC2haxtUcYrqHFGCDt6OHMaL4'
    b'zayTCBsvDLwCVDQMd+gjmv5YEaGMhgrr7Kbqc6fGhJV+CEA7CMqm0A2M9s3rj7zr6JoQDELmwAjfn0VcVebNRD3ZJjJNEk+kqKHO'
    b'o+vHf2sRwjSNZvB703CGvgsb7AisTWTh053hF2EF4SlNQxwWdatsqWsEA3QjHX8rRvN2KPuB0ytJseC/83eroqK7B1IwYAtl5g7K'
    b'wwWYGdfzOGNvzdG+HTEG/DWPp3M2jRdkHRvX7K2Y61uwm6WrlFdAiWIQuUKSiLisWZJzMrSDzBOsnmP+CvZrPM/zr8R+gf0umjSj'
    b'UTno0ap5XtuU3bIzamUz/vGNjYS9S99cZdT6/IfaIJm6rk3skdrtcsDusR44xjlMroDAoCHbGQwCFjoNq/NZ78IgHpcMuS/AYT+j'
    b'pX2ctYezbRk+6xEiJOTuDGMcfFInCXfn8KP5l/CFdhQQiCLa581mQQxH4ocyMgpzrQ9kcGS03d2hxnhNwG/acbwBThjBW3ukQwMd'
    b'sI+peNXTpvQ2sHB6xF7m5ZSzt/o0vAWW0mBo8oxN8nrOKgwbLnx7BPMBpMmARUzOFmA9OD9cxdM76RufLjjLwHVCuBOQTQHyU5hx'
    b'ZpYvFsoeQKzTP22vfnvbq0fs+2aapgNW8i2i1DaziXZGAEGoAMHBiCdspUOSPmL0pBVIkKzQkWSZ3kLcwKxY1eALBI8N2Hq92/80'
    b'AaOf9W9+yw7sETta3MBrRHBoQh5GjwJ9pBntZWKebPuBI6BN86wC2llBBm11N8/SRQ3feD0dDVjFaf+zKq1qiFRCDxaIWgIYdyNT'
    b'cFXgWQR9wvHH9/ykBPMhhslcR/8p7NggVmN2B35x8V0l3erjmgu/dPTZl38afCf2jIErVbC55dR2kDBnAR4XUI6hISEBY5bEZb93'
    b'8uvZsem+gF7pUK2Cq3W14MaAZNyguOZ6WIfyl4aliTtMN6xCNZ0Ho5JKzAM/UJRAoOygiLMkrlTwcDEJTEVmGMXQrutBTNB9kNyA'
    b'rfhHch7GFETMR7DHiuBrXcZoSdJ1a5CHMJlMIW6C9uwwuNUalNYB8wzZzoFz/Yt5Ca5Eyiz11StidUNLUeOid7ckdaAIYYECNvQp'
    b'7fd+7FkhbWcj9Aqd3PWh0WBUx+miPx6odsRfmgtszdYKRJqvailEpsDvka0ArqLJHWU3uY4XxCziwlcHOsawJTz5K9MPNtkukk3o'
    b'bTamUrIgjOo8InUMhXQQ3vTi9RbaKggClGlzM1c9DgtAfXoeHNoELWB2Jm9L6CO0p3JqRmAHZ7Y6rDIwerL6762wCGu3B8eguPfG'
    b'immSgHtHjwWLa7QgJ0bQGINVThxeGTttxoFBazoqY1tszLZYOmD/oqZGZ0C1okHb/qDmKN2B4WBoJNjHxcGBhHx5aQV9FEAgPv6u'
    b'cq4V4/rukO126I962Nq9HKCjfaNgfCmeTGKD/GgmwbehmMYsERWb37pHLJphaiFxxDBujF0BQ3UMg6cJD4oZ9sM9LFYAHduMpNFX'
    b'4EYEc8lklFZZTI2SuqnbUXKkTc5GDakta0HpwJbP2g7Zl0MM2WONdSYUkoqQQ6AFeERUHF9jMEt50kUlniXeVni5BNqIyyJwC5kD'
    b'GhrdWATGgBReTH1F6mUxGiKumriFN5cxlijPIMg8Mu99RLdF+k6iFMgIKh6XU1t4Nn6yFqd86KSgr0eiVvyR2+iSCF9oM9w3qO6L'
    b'sySxz5mmYQYcuPJLuvblvmNonT7PEvmhKwPQuou4fZBHU4T2l6mlqrQ/XeQVP9A6wiHLnL1RRWI7YNLAFELDUZLOZmKJVqDnw1Ir'
    b'SYuYfX4Dl2h/CyvYaVwE/5AvFhHCWBUjfrPsx4tiHh+O2TbL4L2p4xiD/WSc9Y1mAjr8s0lT2A/Z7baGpBJ07Ni5OcTKjncghUQf'
    b'/tlm/TF7zCD6oLO0SZwu7qKag4QHMzCCN0LXPARQ13RGgL+7h7oHRMUWZlqsUCqApD0RALyVjpK/sOew2SFbUcSEhllQ9X7F+Qcu'
    b'sk+ADZgGBJdh4yITkksjj4x9pXftZqMu8oJnEVqXkalKhB8kMCFthZgYlu33mhFAEI2uA5CrjG2sBVbFKD+h42ZsqTTIudloaK/z'
    b'm01HBk02H9g18tfrhvMLQOy8WYmMKLjRlHUcwg0nbgQwDE9fG1dgShh6btGahNIjGYHWhMADo69Swqs+/m4RZFD6wKNX51xxSDIO'
    b'BkGIZw3+Ia3qBOET88RYdnrt8srN8BTTyxiuGw1zYE9DzlNXaM0FhbzVPK3drm5AM230IvYRMGkIQ7P+FpS4W9ejGUzeiMQIyQ0P'
    b'cbpbajiGlAPzizMQnLMtrLstQk3Ie13uAV3ondKQSYYec8vTVGXP0lhVZIMzkzMZr2/PO95ALPVOv+gVt/iex0L9FSmZKMLfdZE6'
    b'SJjPqhCJl+THkUgo39/d30XXbsGkQjTJUbVa6qw3GlKEOXowIxn2F+hlW5CLwA2LzZb5MhoTGKpcTOtoOkes3B07FfcCFZ/uORWf'
    b'BiqOd5+6fe+GOt8XhprSbPDZZDTWyTLH3wwO2CLPrrYksjCZKHPEXpJl9KvnLM7ixV2VEhl5xPovXh39cPLm7NVZ9PLo+fmb0+jV'
    b'89EyGYDy9IYnZhpAZUaO6r/drSe3UupZl3l2xQl8zUqYAqmAy2gMYeJWNctXpbT5wWjN8ziB4QHXVpNV0CMGzf79v/43dsPZDdiM'
    b'TBZphvJbzHK6BbHF2E2aZSirPfnlxdH20S8/vNn+8ecBqgvnPC0FJN1gC1JEJqyABRuxc8jqiopmuUaQ8xUku0t0gpZy3B4CwGhm'
    b'EfUo0gGS4qbkkJq3YuAVVZHguYC4zigbFiDIqfqai3NYMcieW1VsDBZdu/C/vTs2z8v0Q54JFZBGgWcBFNj75pmDLbtPAlX3d564'
    b'uBrCwW/2BQ4u413I/CPOiDyFOxbXuoz3m3X23TpjT6VxoxYqBBvd2bXEUa7qCOvrGWDIs92dHc9hBqGNyNpIBAqdr1AGj1AoxShB'
    b'+Q6heHmzZtP9RtP9rk3l2K1uw42htNEt7s+aXqGw2Snu2ro+7QGPm5Mdd+1XtVX9tjcd+8c8bh/0FRibZBGdK3eS4OsEH0bVPJ3V'
    b'/fEABJKEMPKL4Op4XM8dIL8PAvnODwTnYY4nIkX/7g45fHkYLbP2kO3umOiuhxSJli2AjNoOHKR9Uc2XBUhRIwjjSEtrI7Ccpdoo'
    b'+mCufnDvnC4gVfYtT9b20gqz5HU0Tvy0yqh2nS+i3f1dqmg1NDkI8EdPzGZllY6fEHBXDjFkmYrhA6+uaH/3pkmgACYG3dYwM7go'
    b'9ndvImxVTGuLTElQHSgVVq0xS/zejpGVsh/s5rtDtrUz2munJDtRtcgLLvkawmCHr6En7zIe76opgyyjKuLsEDxKgnIMvox3nzbb'
    b'7D5tabOMpyAnoO62CARJxDAzOI5xmmhg37bAErOcJhiFVExwmrAtAYxmtlx/tVWBKhqBkM0G+Ls77DHbhQgau7R7yIuLki2rBIc3'
    b'mUTFxCSnW9QCAnf2Car84mNOCdDkmpyliJmXh4vGK8nREF6+Q7fW7xu1trAasPwDA7h+HuWTa89rcjCarpYGCz65jqolSOPyyXVo'
    b'VekxMLmOkFQIbJ5csy3ZHNdA/D6KJxXmWBrzrW/VSz4CcLg51/ki1I+s93TPqfd0r1GvqhMvOL3TUOsD1umDKGHLGAaMVwEJPSUw'
    b'vHK+AqXDrIFUOCKgIGpD7DazRQyB9eQWH1rQkJDadBKcdg1ck5WBa0J1x9M9g5qybQtcB6Kkx7XuTrNm4FxGquwahS7RBwQi1llg'
    b'q9Ne5YaV9B7aJeXdqlCDEG9mA0m2DUzwTM56O2+NPY/nao624ijJCFwrYxNV4M3VWh2227mErvNFXKeLtL6DzL6YS07nHId50bT6'
    b'eizbqh/fpBAy2NhHUkxpH3jS55SWLZWSFNh61D7KG5EaDeg4yvgPvfnCzcckK+uuG22mjTYgNGxrsrCaGOEMRBpOkmLhCaIvxsLG'
    b'dTl+om7gutSvjyeSCqyTAszzRRLhixDiIJOQ/gYRKrRkwVNiTzzwFllbCZhpZwlbD/p3wBHs7DkcgQ+C9a6iZrvBZsYYVAZfuRdu'
    b'fm+aRV7VkRokLqtGcGeV2yRaBmOcLxZxCYdAEwBC+K/h1A9CdwOahErqJyTGqyWSYJfYJUk0JkeCJHF4vjTrC1T1JzuU/OQsL0E+'
    b'EImXP2q90cKE8KepiqFVpGDkUM8UvwqUJDmBsApOs/pSmI1QUgxDWosWw2lWo7qfPl76vwr9JnTbVMzowQRUnDxDlxCoYTEORTI6'
    b'ic8l7wBgbAFpT5vZXmTVpWWHBpA+grhzPjiwRbVZnIVBEqKiWQXmfpCrRT400pQJgWsBe6OX+w0cfhodY8mn9eo0DMb0puCZcpoX'
    b'ijN/nC5jyYdyxbSpVkXnJE2Emq3V2A37abd2EzrfNLkNqHzXDQePFAmBG6oYr74LBtVNRQKe5qQ7SJPbESm8heUKYm4gF9HAkuiD'
    b'cbcKdgNQKY8dTkskr5KCcqMdcF+y+9+rFVJLZsCg2GWGigTX6zpeyHFroBcC4oXRXNgCOWcNowiYtZpHV/cjSSescVzC7S/2Q3fd'
    b'UJg0kNnwaBMmI7jwcg3QQKU/16eBAgkeWqv5JVP2Jp5lE0sHRwAbuQvnTQlVAG8uZ2avn7FyxdispcfQqEgqj6wYgZAEInynCeka'
    b'JG8Q0C1d5WjMkxWjtJqlWVrzfoGyDuvLGNGm2GH/5VCy6vLCAQC4iWPx6zYrdsSv+moyaCSQ8f58cKkxQcg/DHQRR9Bf1UEXBxOb'
    b'a2TddmtpkHUT8rjMoqu4iMaJcQt6LkAWT8EVjwswBl32KRxlZU+4WQtM4OpS6i3v/SJBBFWKm1lIyI35+9Fl2eN0im8Sy4CiYU9h'
    b'XjikURYGDF90tnkAEBfQ2Xr9dgvdaSPpar/vT9bBxkJubDtRl4GyWoh8kFI5O9B8kDmECk440aDpqmytSbXE5bEZmfKRKP32ckiV'
    b'GgdRLD0BTblgEIpsqfqaeqk2DSoGzwaLFAEoPy9NVn+YZ0cb9aXJ7UHjCMGMbW/ttSZ9ATxLag/2gCkfYMWhQoPNbN/S5PaiyCtl'
    b'/EZ1iO+pc/zXSxBlPkN7akN5LWtjDDVR3HIxw4dkO7W160ORsKSGyzu0xY6hslwIffyguZhYy2ChC7j/lCgUh38IrQcXO5doj4gV'
    b'gUVIQZ6LtyUtrzZnH3fb+hwsB8NcLaEdDInsOvJilMJJSOUokFFxysDeVaKg9pyELXPZDd/ncQdEBRPFYkecUOHjbl7ZPIYYHsHA'
    b'K1bCSklePWcR5yXMN33ZY408WbC9VmJ6mSK2MRkze0wnxNQpUwNomd12x0o520HoTlJ3xW0QV40ZaIoE/eMwedm/yG4vAVdNQvR7'
    b'35VvQOp06+uQPfe88yG2T6cbv3kPEpILpQLgOVlFSWQ3L0JfVeNMGFBDZ8O45zzF+rJrW1HpI6cGZt5x1tl5v4rLmpcRCGkiNLbK'
    b'+tl7TaqNNKYoiwE5jiDYmJcXhE5xzUf4h0zUsSqj9yDnwo8jtMKHTgdse5vtgaYEq0EVqrolvgA0agNmLHLR3js84x3bOhQNJJgn'
    b'BpMsfICc7JXZe2PB4FKX2W/vhuy98ah7bwP3dO8Zgj2MBmOgMmLOqqSKPqTFJklqYCVwO4bsvecGxVo0OMzueAgx76DNp/cf338a'
    b'fUgLOiKrEo7YrDev66I62N6+ubkZVXw6usqvt8Hru9pOeBlvgxvrtgrru1XVcY1pAregYKvidbX9Efr51DOfJWakKpgjmq1BNbmF'
    b'sODBsGOS9YSYehSn3Aha9HPFy62jK55BfBtI3ljxabSqeBnF8NGIJXSE5G3rOJvmmLXpgPWuPqTFEKxGQdFvhBvu/SGvAF7PWIVe'
    b'MCoO+fW/EJsIARdenr04Y7QORnJ4iVk3ZVrzaHKH78a6LiKIs7EqF0M5w0PxL1wjS56v6sPxs50BBqDnmZk63E52CTMX2S4DK7g2'
    b'xhreppKpkwiJ1vZV/0NaRLCTB4h5tqTWYPKspLHUAVqTfUgLwKPR/5IWL9MFV+AGkJjggx4JVR4hE9mrVpNRfVv3sNLMyXO7mhjR'
    b'5KbVdX82ZBXEr/03CMq/QAXHMi/vzJiLjR6y1TLYQ7Zabt6DtFFdTYYAQKxmUfIiqlYTiGHeyWcBIvFidOo4qeYQuXKavoN/yG4U'
    b'fpthvr5ZgQGqxdWNX/JyCf8C+olwu3QMq9UEo6tbcXRJwySbe2QpToWw/OFCji0ERBa3gYBZYvxU6SwUTdN38obWNaRgQyltDBA4'
    b'f2U/Q381kjmgKkYvgahttkirNOsfPX9+/NP58Yvo7Ph59PLN6Y9ntmuhpuG4wdlq2c9Wy/ttcB1fwT8JRm4est77uqwwI2OO24mB'
    b'vqz9zFbLwH4SjNA+iNK2bcC+m3FpjbK21mKo/uaisN15X6+r4D8Wd5CO7yaCVCvRXZ30vQESm6uMYe9nTrxscZTEgtM50hg+8PMK'
    b'/WkKqW1Bhz+7GwwZhNVhiXLm9kC9HKLrqcwMQl6lglRoQgNWEVfOAN3BwA/wZ+L6x8uensZ2Vm5YIk/WrmhIsWmvMBwtRI5xRdGw'
    b'p+JtWcodxsAjhRQtGZ+RvbaZG/IXLdXuWoXAIwF823vaHDOJTRpFMOULaHrpqdBMViubwDoC7pX8GkNYYedbbGyrxP1jkEp8zINp'
    b'TF9+HHgzYnYaMG6OilQEpggaBwgJjGNMXy96UA9PErb2MahXV5YML1/V3SKnomezfjTBo092Zx1FbVyRr2pffBoMHnwGOZjZXrKV'
    b'auv93Z3BAYtmC36bThY8AgOgxyyaxlclHWP88MUjjEcntMyrDOLCZnwRJbxMrzmo0+lNt8yvKfBJOd7Z2ZHP+GpU3I2gew7BSdQn'
    b'1tPj6UF8tek7wVuRozpkdFlUEBKpmuYFRnKswCEZeKIvHonYnmyPZRyjXc/5AmzhWT8C67totgDWJa+GLFqAOWsWw5kCj11wwB9+'
    b'8YhFK4i/Q6VXZX4DXA5a2ScwKeHq8C17vjf64gt5f+CsRYYHJHXT/JqXMSS1gCIPtTNEEICqUMuUMuAHQzomrl+VGweLQwKyHSHe'
    b'RH2EqKldH9uueqMwnJ/IYjhkU3HNg4gi4bMYsoknJmUWrTExhpega97IIKCNbAeKhWgkO5AZQcwcPb0SjMFWHD1ukK1CYcY0X3L5'
    b'JS/MDxh1bmq5t11agSnyRXi5MVQ3joHkBMnF9FLJ9sn4g4wCsAOdJUeAoUZEnLA2waNodQI20i/oz4obQioyDgYeRZyWwHVVvlco'
    b'2lB4EHLIgE8DmmIEftQCAvhL6LkWCwTe4PGQHslfLJImmwSjecyMYZknQH8NyNskZBF4Dx5R7kKA9zlUGVwKF0OhRo98p6KVe00c'
    b'3lX6Cf8WR6oJYC0Hbz1pU9RWYNZUq+0I9Am9+kNviIs88IdC8h5yB0zAO7pDFFOdychMCYVLO/h8uqCr+ygEiHIfDpcEmRdpiCSh'
    b'sUiKTXGwaDrD52Bc8FvBaElBmzf0ZuvmYkvcUQgxu35XZU8khLv3Ftpg3MAQdupZpHbAejsMt9gtzWGbPLWPqfZjgcNzqcQ0V1cy'
    b'MpNTFoU19SoxhUZ0FPHueM6cJG5mIiLl/nwSn6teqzpeUGgLJT2mbUO3W2tEgxFFszAZV7cK9fEt/9Z6NACzocDbMhB9mYg7Sa7M'
    b'k4HvcpKX39WVLY7fGe3oi0shvvG+McRa9TICiQtgiLjR6AHpYRBoevDeAtZRtewJN2Cx/C2rLW9eiXiSrbYWwZMQDrAPtURwZw1G'
    b'H9A5erzjmKRiVbnA0ZP3kHJd/OWraM/hQK+Ep7LGCxyH/KM9FxzIa6twKFEMSxvX1cOROBFGWV75QisNMXIlMLBWhb+xY0HHTXGN'
    b'kL3f8BhSFlEtNTDZylm5S/Z7tjPa1yj1V13T2AyoJvQxnqmomvUcrJ/zRTLwATT2AeyNw/B0RQHHktuI+cE/Ft1SPTYmCUhvTGZo'
    b'oYQQGJqG5tWUY87GwwsM0UaB2pgQTsAforK0sCsTXiKVs/bwMQ7Rs0926LqKc4zwpoIhm9G8LMKOceyoLzsXBxUBoDVmc1BlFCcJ'
    b'nkTjK3UoDzQWCpwERbYaDthAYy4diZAYWam/j6En6v7OaLzPvmZWDSeGkBnUzARumBnmBcbhodNl30utm+gi9rC5j+YO2ga8Ygmx'
    b'c8+O2cvatuTeZQ8vfXD5nf7stQM3VO/iyR80u//CErKLuh0JEj54SPtiSBqEzw9uQ8mLvKyDxgGhlzgUHzwoSwcj0JozGhapzXqN'
    b'oT95bwsMRtPqutdFLGBwZuZ94Jw2kSNUcseCodDclJDQVpEKD9q7BGHSrPdx+il68h7G1fPd/UriJCqhP4ohO0RrNtC6wCo4WWpk'
    b'HSmkiuu5fp/9Yz3Ngs8V46nR/nC5fGC+WLBvLu87za9RuWptHDIsyPV9PrenuRFob/GcBptJgoD8uhqJ5QByiz3B+B6AaYNVa5bZ'
    b'eE2snWUeA+JYuSHk6jiQEeXwSWUWy3VCW0oas524RnXrOT1EzIA4Xl0NPAzl11/DSoQYTfMsHaiFbmcLm+yg744yISv+wryPrJto'
    b'zeG1Di4S5riu4+ncpMyQqy9K0vgqy6s6nVYUFXZx54qeQmTZrw7ypIKHPpqpuonSWngRIYldLExbAbOWstUO1QPLuby8izzb7lYV'
    b'JD6+iZqr761qsIZOOZRMV8sI0k1BhBgwkEi8taAUnjLhGuthqBrxlWRknFp8NuNTiCSjFqylirxpwjBC3SD+AMu1CpSBTaDR8jIo'
    b'41G0TGFKk3lqSRIqf0CcaycH9WUd7nZl/32GROTBd6cWa+5UWS7PfmHeqUXbnVqsvVOLdnGnVRwCAc1+S3Hhg7KDkgghZliR+vxT'
    b'MO1BbCYCfjZQiWB14cTs5QuDtyz8M97x5bZXV2w3AqvaqUkddCa6vstu0FjRCz8VbcnLa7amNEnOQ824th30C7kXA3Fv4/CKh+Hw'
    b'og35pfFOZzHXmktLcpKNliEx44OKFxUOtCMHjLYZ8V+umwwziedlvLPuQQE1vE+KR+wn0jhz9tOr8y3MEAh6ZmIOWMKLes5AR456'
    b'6LjKZwzuqxE75VtLXl5hUqeEZ3UKacfuBEw4pIk8mNTcohs3+QqSj61ms/SWxTfxHUJH39IZhBrEcOzL+J2MGGfkTTSYsG30d0/A'
    b'0ADSwGDUOQZxo53hp5UUHI2MdxCM3qAk1im0NuYihI0hzOtMRjYgHZfeQAHZYWMo8/xGeNhIGZo7ZUKsodnaaKXESWu5xPZU5Ota'
    b'u6nJu7UIJSfv0HodGcT/GxqVzWwBLKOJ7lBaMUA9+j1sIgZnMIUmjijAjsYf5D3gZ0vNWtwHCQQsvyP9GFASmYAQVaeCmFD49QH7'
    b'q/nNlMGi0eLHHpl/4isNeMjeJ+pX0pmm36CxmmSGLTk+d5msBpoFN1U2a6OxhLU5sDmOvYWMUbsBhIaFxj1g5AXkwLlKsxCIYAgX'
    b'9fRfLKxQLiIp6CKecHJ4lPdGEllFMkS2yFEZLeMKFR8qp+hNXib4tW+1G7KzYwx2+sPR+XH08tXJ0cnzV0evoz8e//qnN6cvZEJs'
    b'abpP2xUh4a8+f9fiCmz/77fWizSeQNygFDnj/6ANL3MeFWV+e3fP5p+Ntfl0timuOTtq6U29+6yQE/xrBXKC3J38Usz2nqMtXA7/'
    b'ZiLm0Ne9MDkwpAlkrNwy+ZD8AbW44L6sQErhQneQjsDCBpm08P565p646RdNEYO4XEkpETpGBmm3sUMS5y+NfaDf5QS61pdruLZ+'
    b'qEL/b3ovnRBLfxO1wJXavC+8yGrPvGfoER0+qyegRuCaYW3a2opysusqhsqz3FdqTi2arGqoVqQQV6qeznveyQrcO+xBVWwO0SH0'
    b'XC2xZ9JQRomA1E2ZZ0gX5ZWFOtqoNVokq09x0RtdW3ok0Z0plpKC1M11SU2mXCTb9bDrJ+DG4rN/oBzhww3eCQ571iZiCIstQi8K'
    b'v7BxvdCxWauTjPgesuLNZMLdZcPNmt1htsmKN5AZh6qG96yKF7wiY/S9uzUV9r0VtNlvCxSnkh+Swb+0gHJr+WHZjEgrlEANh/Vt'
    b'VuBFqKQKlsymsztP2QMoe33qnOZLzKu57fhck5QR0zc2WxmBk5X1YHLhHcOhhiWNf3zGepBQD6VaiTkr6TD2RZhousSySSQbxDFM'
    b'FH3EsEkEfwsl2aZ6G136T/XaA6jXQqQxSBJbSWErCWwnfe0kL0TqwiQuSNqaJK1JynwkrEexP03toRJCw3G1Ddqk6E4YoXpVcsKE'
    b'2NXJKcIiysnt09HRN46OHF/QakzIx8WAwgSYBBgQXRTDCLryW99biIw3omm+yuqqb/k+Cn1SBA/QfrMplFcyYkgfagI9XmVSSjow'
    b'R2MOuiuLK5sCe9vJMqHJpU/zBTzyIL5xvEpS8doLsOpauOYLkeq3aTAvHi0pOrBCQGk3e3YozEuQ/3f6JwQTk446PgncCY7+UuUZ'
    b'PQbkM25zSLKlPADyeUHca0d4lliyyuKimucC1mfYvCn2w5xdgA3xN9STCDQzd0DEgKj5bd2HlR0lq2VR9T/KhyeMtHcgTHR7AkXU'
    b'53VvsU80gqw+3DVMlgVe22q+1k0HzZ8xaOeN3GmTYbTmioZBePe1d2Agh2786Z92CZ/lxuSYE2xiRNDNdkDyrcbxbrKvthzIw1r6'
    b'uJcqX2n1EdWq8pl8K5vfZeQiPIyfwyn+pnZV2ibEwzH5uRqrKtiKGEuKNiMdeKTP4fEcUFeY06co81la+8uI53KmCNnKgSx4C2VX'
    b'5Dwd3eUPxG6CkD0AczrzQpOfG4vhZyTDvKdR4h/BPVlhh+3Uh62N+VTeq0EWVOjk/YyoKNR9XXa6BeHMRWQdsKllTdtxDYa9tWCR'
    b'+cVauxyL1zV5uaMMA1MboaeE0C2/qQyT3cLsQlQB/wNRRflhZKssfb/C/NS6ujlgs5VtrNQVgKJbEJcgzZUBzjpvOmoe9KkTpjjB'
    b'YZv08HM79hDXToNQ5PZzB+DTR63rnK4o8fTpHXhQWl5iBuZSiFt0eJOmYb1V9i7LbzIdfxB1/NbDCtlPQNJ+KxpI15Degcv/WReE'
    b'XCcb36wqXpMsu0qIzChLLYcLbFwg/mE0qvmH0qi26XDsi84/Fifkg3cgdp17jMK4YYKjMOoER2HU2XQUznXmH4ZTyT8Op9L9cETy'
    b'Cm0IIuu0YYess/mmuFxLaGPceqHNcettMKJPoQMv2IvwmScez+BC/LNoVPNPolFt01W1edG2scg6bQORdT5jFPsdRrHfYRT7m4/C'
    b'y/quo0Frt8hb9f5Da9+qZr11g7rvljVZ/U4jCm5ds95n0Mu1++evu5Z6fsYOel4Ya4fWvoeeip87qOAueip2G9R9jqH9TgyglV0p'
    b'gFN2pfsMZM1xM2qEh3DvI2a8f9f0Hz5WRo2HuN/kWxBfks3brflEjJY8SQ0PBP0OHVGJxcyHgBS7+z4I71dxVkNA253R7n4nON+s'
    b'g/NNE84MVHWYu13O3n7ZGIAg9+2OekRYuWUHjdUVktT7G/hsIjgXr+oLR6ANz2qQdG8iKRdV/gcRdP8PZefQjKLUbtGvQgA5zgGW'
    b'btKjEu8KNtTe0wsprbQtk+0vIKs21mtr/Vg9TgJWG2VbiYrSy88z6FZT91s1Cy+EtlScHWAHLOwfBnjIInwN9KBRv2Evbcc1+rsb'
    b'5aw1kLEx4Td0Kt9Qg/KP5H/untM1Oqd/GtW0qH/uoQq5r7XN/bRJkP0nza6UiAI8FmybM5HbtuDNsoJfWR8dbYtJBh7Y2MdwABP1'
    b'GheJl/JLz4bLC3NwtrGQvhG8NMNHZdbTD3+sMSMmiBNlrDnVDqzkF2v4SKxmVxJ9eDilRogXzZeYkV2CbIvKPdXoC3RC0IPUCtF3'
    b'waO6tY11lkoDaCswR+vA7P14SNWBd1hyFwKTkeViUiusazi1OSZrRpEZXhR9jnVkRqMWvTpMLAFMu045RGpv1tZcZmgkuGXqOCp2'
    b'0522FJtGk7hKaeK9BjDNt6/tsQeHRS4Z4WvP33GZoj+3Ftw6+kavqmatSkuuWpidc97sQdp+ny5DXF64z4DKYZNOg9xfuFf/JXGf'
    b'zgPXTYcxNO6h+3TfvMw69Kxvuft0adyRHfrya3I26c9hAzrhcUhvsxkuN7iM9r4/BQjMsij5nGcVPPECh316jwFOg8NRYTOcNg3p'
    b'm+pfcTjP3/z40+nxH45Pzl79chy9/PnkxdGPxyfnR6+j529+OT49+uE4ev7m9c8/npxtPGXBNjTjDrvB4LquoBEwjngMDGjbdfmt'
    b'NWhchign9D7wafC2OUu7VMCTYFDJIWVcTMExNNKNfIZsrCEXu59M7DPlYfeShX0SltiTVbpIzBBxwsdSsLTNhAVr7bI9aQuoQD1r'
    b'6zya8Xo6pyR7XwQiy0FsWDt8z3sAyA69GRQbwIUvd14yyDcIBw+b6/fCBxAzeBMFitSAQ2yppaDpDNo08nR6Q7la4eEJyyh7GST1'
    b'aeSBM/LLhWO9e/sRKduMXGgalEi2ZqTREty+bggJzOA/YQGFwS5UxgjtSoaHfuJKra0BOb1CJi34j3JxCcjYk/igbK0uQy0h7ZNo'
    b'eHJ8/OL4RXR+9MOZPSrINddpVBgyBhNcr5YifgyM5r7J4C4vKe6MaO2GndE9immAtNn8e7SMiz7kNIQ5Rc+PTt6cqJeGVVHDm2AK'
    b'JlFoA8M1+v7otVggN0aVyMUUbvry9Zs/OW3NbilPFcVm6qu/e5cq4BalmFcPI8iY6Qx7Ei/WRYYTWb6oKytSnMfXxhNv23S/sTte'
    b'Z88tOlcG17O01PHmjAWEfyCU1o27AOPBaMLrG86z/njInjgomtfY0oenAnAoI5ud0soZScf13GwZL8PdffYqYk6m9Dqvo5s04f3E'
    b'jTl6TZcfxkYLXAnGsjYCSnbJ0BUIAyx/8EIY0RiRNPdJUuJxAJAQxTLTNhyKKQxZfHU1W2VTZbxv+l85fSqOEdMkQTLxKs2qGuQq'
    b'/SlkeC8Fy4Ih44xcRaqlnRtOzl8vfDydClLfGpDxUoZUHjgt4+n0Nw/rCD+AFnBhaRyZxGA6ShnwBoJsG8WAlyJmf2+ABNnTF9Lm'
    b'fAWuDAO3K/hHgI2n01YIDnWHlhe2owRyrr2Pd5/+9eN7kazXZGNkhEBoabpxWIolWdmXFQ5wQ/FEMq+JoTa2fLUC+SawzOkcq4uA'
    b'lCoG5fUBe4eo9m7IrgHb5GV1BhkPl1V/ICJgCcBdMs4Zcb7QKFjTV9RPSA7uEILOa9WDVabbSNFjqK2/XJmkG7zvnQy/o8kwju/e'
    b'DDDpqzB44TIuzEqaF8ZAKMTKoxdjFy/EJj3s9XrfwxyYnIO+SsT+whbSeCrK0lvkeQlxrZiKbd/r9axsarOr0Z3C6sVdREmmeQYE'
    b'MZEJ0p05NvDMxkxaSYSTpKWbv3qZVlPySmz2KwR78YxHy3dJWvYVFAG15DPIJRJNKS+2L19TM6sS5KSkmglf1HEfHpGIOtYAJGhM'
    b'MPKFCjOZ5iBW/MA96yp3VS0u4UoOTyr5RJet1Ksmf9f8ptADXmIUcQfSgVv5P9KZg0VeKbBdReTpgUKkc3CynRoNvQrsMQm4IYqV'
    b'XdkKoDoww7VL/t542LRNSXdyYfT33SF7dkl+JlYCGxEKWOH2UCXmsNBSkipLjyQjr1pTt8dkMxV6fyQJpz+NqTUSp3q33G1Ou0+J'
    b'WgwUMMikD4o5l0meL/oy8xg+XHteDM4zIGomtB6xfYaND90oXlR9bKyBJKCa0Okntx1ol0qNZDQShF4qPNdw8UBsMCwclbxYxFPe'
    b'723DJRwh7yS+/Nu/iU8aNZEYCDdnTV+24R5WsD+Nirh8v+K1vpNBeKeajigolZvAt/GCh58lmLY4dKZvgAJdEgSDqyOsOWSrLK0P'
    b'e5UxZmMMBO27Q5OINfsMpoppFxVY6eF8u+VFR8+Wup8uDpp3BOSEkfUKXkblKhPpqtJZA4Ae5yK/6s96FyaoS/YS6gAR/QhSO7fx'
    b'4JOiu32s4EXZwSfIJb8lPw/YaDQy9gDQMx0aGMpRzAgKSre/IRs7iPG5SPs5iBtETIywjAP28TOAlhwEhFWDdhnoCNdFMgu9q6gX'
    b'EMmKURl4H7BObE8sjQjqf6Vp3+hNu3PPBIsr5unbi3gfaW0+HbCP/JOzYfAuY//CdndQ1NEECCd5VC04L/pg1CcOCH5AF7d9g9K2'
    b'DyL9tB1C/AQizw46nB4GzPiC1/xg3SGS769H7HUeJ/C+IHRMwJAvDshh73Hx/gdSemRq11H79QJcGcMcpbdNnGygizxJvkzROkk4'
    b'lMIOJTMSonXMEkbwBQyVJw4g6MPTEVQy02knJG/UqCDcK1F1L+lLr1Gr8RwO1HWfxMlsY/m3+WKR4Ox7xT0YJ7nvlYQsKCgAlPnp'
    b'mlfMZm923aQ1PYddIZRfg2q1pulwqwRAZTJ7pN//WdQRhx4vWagnDIx8VAeIB0/YR2r0iRJrAZn4SF19Ys9f/VFyQf+ZRQYiubeV'
    b'MU7wbp+jM4OUAb54RV5dmi8JeK/XO6WBMGD2MQ8B5j1ErwNh9/b81R9BDFjxmt3MeSYpveSS4P0YLyju7ZzHi3p+p4QDYIqzaZZx'
    b'1WZNmnE3wbhBN/GNKogmFjVepwKi6otOKeYTlxlSed33DBnBoSkYCfz81l+StCqFr95sY0/01WjKDEDnEt+COgT5AcD2OLubxdO6'
    b'smULQyYylhgpJj2LJ/JJGsvhVHBHGMwU2bgIIJm9OfLfN66ie8PF4YL7JtyUCKNvrYQoAD8doXUFsENrPIMNxqKoi64jzi7qefMy'
    b'WhVAMI0z/PCqblcEqMR7tixwrYBPeWmZgbxmPK5XJY/AWJw3MlgKezyLE8JT1uReDOhkJaH/VmxSUNJM+IcJBy2bAytxJp4ylSva'
    b'ONyuEYbILSqJrnN0UFmuNPwcktqVq2xA6WQV/Zb02ILkObjAQYqNM8mVMTqQj6n5QeLj3R37GEKXOYSkmK0WC/s2QKGyY5WM7Mif'
    b'jk5PLtmxFBHqRhYBrvMcnq6/A1owpXqLBUrfmYBtPmTtzXW3yP/2ElRXzW1n36dECy+XOzPvw27Wdb7SRnNxB9Nm/Y9ybAej8b98'
    b'GvyO2ayj/OmVqwyMAtmkhHcLbTqLp2DIhpcfLhteeLxmEz7LS85KXq2W0EimtJXzHDU7cZ6VC7HrbjJclKxB/mYPKfYspGAfXCjI'
    b'O6D8DmaPFNC4TsNb2XWrvNs02xAlO+3NTG2M2BIxPNb/6BzMT8oeaOiFgw9Xc3ID8TBWi/MJJluBILeqeZywfEa7rs6JBXXQctaV'
    b'Pbqc4MAmAd8dIg1QQvUNzr8fAUL8o2l8FEIF465u4lxgp1+uYJakJMimJcqC4oWEI6QEaxbbx05Wnq3rqUzgwM6cHT/fRupVxCV6'
    b'JPh2xY/dSDbXjbzkaCsueVmjO0zQldbzfFUbVEIMQrzm3sOJCV4woXur2UI6WX0Gjv3+3igGk3AOF3EnJpsl362k82wWabs/Ewct'
    b'lHAxL8ga4NrYHfoMDEMdgdFd574yfqO6mubLSZqZnF1l85oiGJUeH/bTx/Vu1NPPEDThUW3oe5gxEvdrw8dbDFIN+At1sahPoTbi'
    b'6aOsuuyz0jZ9BZroiUyW55GEVKuiWODxOmCAyhW7iosKHoolR4Uxikp0Djpbut/UBN/NHBQI6tlNPLChDR1946EhhxDdq258yk9Z'
    b'6JNpt62aWDHZfAPTChPyfzIBhxqEKXQ3ngRtgZ3RqoRyToMMEP2qDKtkMU2kdcnMJ+gQZhDNAsv9FNRM0ugbjYfZIRs/2wk+nySr'
    b'29RqiJGL0nvmCbaEcY/Z8zenrj0/mvGzxwy+RufnP0Yvj16//v7o+R+NMienj8fp1p+dw1PTm5yje2qQbulGOiYP6ZQ4pEPiaUeO'
    b'bXqCyr0NpmIWFdoSMksMwO9gIKyB/lZRIWzLKzMBtCGNDSaBNuqoRNAIyEwG/XCi4qbwuiXCg6CbsrZvuu1xkYVBpoWCMtnzVB+8'
    b'8HGSbjmWLculArrkddxMSz9tPdqWoaOKM+kESfaE9gy54FvWwc3BYinVMcmdIREJksQBKKuFsdV8lb0LZj5OLMMdzJzqzX1MrroY'
    b'4QHka/YBE4mRHWNzaxUDFkW+s6zTD/s1xZi8uHmK9VylIPDqao1MUuVev7DPm1Z/6R0SczSR1j3ljZTQsGheY+9/yFVRX8HAFSZ7'
    b'ZRsrNyxDexT9+4D1wJ+XR2lyK7Ohwg+6nIgUvRGcEfs5Cr3YV4AdKt0IOTNsNIzA5aI15ViZXs2pWuBWStKSnKsOe3B8wLHTqGFP'
    b'YznS62BMdkADlsbcGq/grMPsL8IehkUoBjAEGWg4boiHJAI2XpIN6ujg2aR9C+RqXlwYk0JfZvv2MqIPWFO8sAnp4+Z4Lrttafdt'
    b'7bS167cXtziwqc0lnE0auA8+pD2c7iT6OP3UMxKkT5RGH8/vfzlsLOgnfx9gLm+YvoR5CNIuOyMlPAV+u4/jpYktZWzuL5wuO6Z0'
    b'XoIzB03TCc5kgroCsXPf4SuWXdggtmWOxQ7CJH+u40WaRGKVGtmS2ZdiCBCcbcf4c8H71pVoj9pka+mUCJ2fcCIifkos35CRJhCs'
    b'LAMX3Jqj6JLzZTs1XwaJuVjyaQ6MlIWCvv5EzW6deo1CsGBVlhyfWLYnLoyyJQ23u9ae9jS+LkBWFScUUNjwpRyXzNz9perJyqTt'
    b'LAkBGsXZnWv5oxZ/tMinF1RvyHAjFGBdYvvahPDK/vuvonf7MC4v2p56lw7aU6ZguQqorT6JzwfrIXZj3I0DL3n3+3dp+3LTsXSB'
    b'Cbf69cCIZXbX1JM/2IWyeXw6WIQAuWsC7b6u1mOoZZT+EHfy555ktm01nHvRR4QBcVXTBmJ/6RlVG057vPR9R1YcV9Vv6NTqE6uq'
    b'tgQX9LyB19CBBtTQtLxwvMkwrBW/34TCZmSfNR1lfPZ3nYyF9IH8JffaHB0Z4nPn09RLrafcRCo3Is5dm1gr5uEU2omoGZDErP1P'
    b'YvmZxJL4cJuXNwRWigdDdhDcRMq6AuVkX167vUEbq28/5pdUAIpN0xCVKgXNUCFwtJoPuuWsVBQ98gjDyesqgn80qulz8Ij9NAe7'
    b'k/H+1nM2S28P2DKu3rHxt9/sbO2Mt3bGjBf5dM7QoHueLxIw6okrdhKfjxSQfCUDurRRaazVeokQc2FLFTaEASp+y6mnN/72WzEV'
    b'991KR9WVGsDySjPv4OI6duB/j6UN3xdYJ2x03HVZwxAeZlGFyDW8qLJC26Lq9TBM2fGj/FufEVOw23JOrGrd+m4YyBNeWl+/MJQT'
    b'+aq2XJVXWXrNy4rLsHegOiXTRPZXy3QxoA+bzkCeCTEhZ1fQVgro6zmIiq84KfpQM6+NvXsCHbd3D2gYYG4hY5vLEQkHK2yEkdOX'
    b'fDnhZTVPQdyKlpcU3Rbj8el5qFqGFpi6nsZZkgKmVdpqQX5SABqttBulbn8hIwjrCAcq/Iwy8MXWPKvAsLIo0ylmHAGTksgwO/Go'
    b'qqVnsDSUCdhHG4MhifulNi02Bi4V3/CqgDiS+gJQAOQcyJD7UE2OYtgAZH1tNGIxyMqDC087fceJsF/24tjanLAxrblGcgFcxf6h'
    b'/adYgpIr+zNbO2bpZpWWP2SAoZMLK4uZKc+EZSqFDpOmxkK9L87cJF4gbUNlCyB4BAOqyxhQHrkuNDbF2xsrDtFMByrBX5aFmQHN'
    b'0DrHacXZ6SoD6nkM1LLfO8nVYVIvOnxSVuwGTC+ueIaeiWj3GXDIIgeWqLiNpiiwISZPejl6HRzBADku60PTu7G4lRtb3MoVsg3P'
    b'iltLO37bGnxJfrBH9/iQjVVRzadg4Z0uIAm2tJbAvyMsoigsxa01CN2oU/e0k+i+ZbSUolLCH7zOXuEHY+MGQ7bk9TxPDntoMhEM'
    b'5EIJ26znuJK+id79QjgMkiPEem7Nix2b6TTmoaq6AmoF76BN/Cyba8IIa/NFyD1LVrfmC96Q432fO6ThCmm6QQ7W+Gx5zoYF1jwo'
    b'sI/kYwQXQz1yrBBnPYlyQMiJjleHHy08/KQI+KHpIjn45ALrPZ/z6TvpQYg3A5sh14XMwHTB4xIshWZxulCe/hA7UFsd1+WdYfYo'
    b'492LuWzkSqYbyeQVFL1GXw8Ul0zRdjd2jWimbqGQmYFbT4nGRbeGsQEgv7rQDWZNp9dwEF/BdlthmLRgoYy2Ze+OwVVoZgLdSXoS'
    b'1xx+xLTk7AlhcjTNs6pO6xX4SEOqw9s7c8OacoDWOfzWg2oD0RgiBHAqisVdFBxUzUu530MXqIt2BGrB4wS8/Hk1XUFY5+k7EYw5'
    b'4RKgyQWI5g1YflMxNRRhTWKbvnntHtyzgZpPYieEs0wVpVmdK75Z9WHwHI3h1TXYARt8BI41SeOrLK/qdOoO1eQ+qhoGp8IS2FxH'
    b'012np2bbYkTmyR/oiQfdK3MukOXSJjUXveW7ehoXHmGbqlHceh9yX/vri9yr87jkFUTg8upzXOSJkzJaVUlEg6Gh6pV0GXqdR0kP'
    b'3wnGi6bTe8YtZPrboDE4jdByakAfGxwQepHkqwwcWH+N53nOlnH5jtfP44Lh4LQeyAzvCJHRxHvBmokH8Ts9QIZo7pPxm8OnO8Id'
    b'0Djry6mP1wldB8upxd+b41OhK4NXRIPEGVjT3ApBlAPoZPfcRJCG4L9Hax9Bq0V67fBRvtukOVwHQkhQ2lY/NB23qkdq4rul4Oee'
    b'K2TLHelAURPyvaNYyeuOCDUEubloTFQadlQDIy+Xfaz6iL1GwrSFkPGtcA3p0TJ2tYrLhPVfgqfNKbkisN1v9va+ebbzzf6zZ0O2'
    b'u7P7dGvn6dZ4PDhgFELiEcRLTLaQh2LgWAGUlCfyXMJDReS+YZNVTaZI4MQlov7LMMYC1t++ffYv7CQ+EWMH2zWsjad7sVBRX7QK'
    b'Op7k15xl/JqXwHLzBFg3AQ09pac5fFTCDIjBHBeg4qpz9oQBj12x/quTX45ev3oR/Xzy6pfj07PjwYidAm8HIAQwm44I6pGX7C+r'
    b'imaEC8kTMTOxugj/d/i0UZCoJK1YVaeLhWoXz2DbANIyzbamcQG2+jUE4ijj7B1Laza5YwkMvxSAruHAcNNJCmhQAVQvrUfsD+To'
    b'DbtSiRXiGfTB03rOSzYp42w6J8GimXMhAqHk0P5EGGnXUuhF/qAWK2DVpEFH1/lCXfJW9hGhFbTxFz1oIAhWY2ikNCQfm8YgfReG'
    b'84IQ14e1T9S3vkY+uoDRL45dVxIV2Uc9fyxzXeZ6+DjocANBxJXmgbBeFfK3jKMNgj0hST5BfdZYK/alh7CTeQXYBYi7y4LXjBWK'
    b'X40gbXZBIxwcfrXkS/YsOt2vMFV9b453Wy5Oktxa1Bavlan/RsEaQhK3lpZPg3I2O9SpaXqmBHGb3QDhtRcLauafaa4q/MAFZXAM'
    b'Xowwtt1KdwNhq9XSeNmFILwmF7G2qrxL4Z9BkAh4HmWtHAupNZp1vyNXwGWaCfhNKxXVqILn8pLXZTr196KaRE0aGRER34RSirlv'
    b'TupEX+hc6Ph5d6C+Vg7RLpvsrssalf46cMaodnd8KqYWNG/3efbRdfum7X/0ryX5PouLmKgzEnGfN3QPLmV0ONe0m7pUt7S8nwUP'
    b'o1iQJOck6pa8yMgH/3wONW+yqi55vGQuhwLcYV6KicFjJ+Xgzm3yPPmqLlbmRRKSeIi4P7R87k2oXcTNC28XncQBn/CGA5yqczHv'
    b'ret8wQBdQMRaplPrbRU6ZgEeei2aiHewEFvACz4qSimq8GeCRctgvBzNC8B+KBsB8A3igTJCPZkvWXigfgB2LT8kLNzfNWB8y78d'
    b'QNwWhBLfUvP93cBAkmh8F26LxabWZw3dpc8qW6WX7LqWXjreSJAC2fTqEXvBr0qMM+WwQQd4y9pnGqXDcPxwQJM7B5R9+HzMMZyR'
    b'm3m+4OLE5pnx5tCK9tD83U9/bXLPCobGtS+bLf1y3wvVxvIaaAoEbH8r18reodieFAFmWgC1qbCuEbS0rnPlU+R6yDgHeQTN+0qz'
    b'gnkCzJ4NB1PzxEIr5Gw9p7W5Pt6xChTXMtv0A7fWj4R3sldk6gxxn9ow4EG11gx5UV2mRfGadnoJj7+cpqnLpGRMfWgcxMPGFxWz'
    b'zFmbuOZlSrJ+SpkblXwRo6UT3CDZVT3XfId4P5L2f3e0d8B4VqbTOb0+BdAZ6F0pArbyKU+zZFXBuxicRNBrvMoFMOOukoJZWDCp'
    b'+lNNtxb8mkOUBxodk6Mz3u20Zij4Zuw5ShZAJlMBV/9WBxbfvptFEmokBySjI739nQB2wylsmoxWIs0ISM9Tz+OMvW1AsYJ4vSWS'
    b'8IgdbX/P6vzqasEP2E9/ODo7jvD/u9Grkxc/n52f/hodnxx9//r4xeEOq96lBYWrUYuH8TkFKHT2mXNWz0turM3pGds2ps+2WZnX'
    b'JJxBcQxqd0GOgve+nCFgdsU+8DI3LYdkIgvgP4zNAY3dNchBlkVeYUOgsFpiksqGrJrO+TKmyYOCGLAlSisZL77fwy+7ag96QyaM'
    b'o0mtZTgbmuurH3+NZbe5Ousoeo6jRbeaYljzcdMUydpQxDMTXDDtmNtNzBB1ZSzk3pDt7u+YCfTgx0SfTlDNBr0he2pBbLBPWoXR'
    b'XEIlbreKvCASsIARlVqoRbOlVOfnGU8Xgqaiygk5z7aWdp8Ct6Mqvcrihd2uyaLa4pULB/suWZJWlMjgOo0Zz67XnlFHYPPv//W/'
    b'4bFFHkGdWkXpKGj2Y00Dw4fVK7wBQU9U7MICo1lAmrG+wgS4r9W64G2LN/hqoio4VvLpzAK2qSjdaItqTT1gKAFSIn2pnWUvQd0m'
    b'xjkmpZTxZa/x5Wnjy3jXzFPdAIqT94Cm73sd2ja7FDCbHeszkoPjY5yJGTS/Pw18bwNK3YZAO6VPO8Np63ICnqf1PEKxeLSMd3cw'
    b'45YDylurtXNJFeiEWyCBQ0gzpTiOs3cuLD+ZsIA4pMDruCsPkDg8FqJ6D8d9D4Y4FNKi/hHb+twfi+Hah2SRky1FR2hhthfx1RXq'
    b'X4hsnb45evHj0U/s//1/dkf7A8mCvOBgt1PBk8XeIYMwebeMQeoxm+9D7UpasyVoMCABsKGCEFXYZJFLJcuInSPvI4AUcV3zErK6'
    b'44Nctjig+LMNWnwdl0NkUbZQSKm1IcQBiZVZx7MknD1GfgU3XfI/87TmaKDZf5Vdx2UaZzV79GwgdB4VBzaLL8GQWuZOf9B9DfNG'
    b'+/JUiL01OCQ3HkNU7MvGYMILhrHNDCDVaqKJmg1aNm5m/8DDYAG3sR8KQTZxVYJEvMmsWJ1SRUQveHcN2VNH0QvQruIiquelUmGu'
    b'n4RowStgXdFv/pkD12Yh2haCKIjxpHNAND2C7EkdGgvSrGuNFKuKL44v+rrgdxdeBHGYGEAE4ErUuaEERBQa3nXbRuq4L6kjEpH9'
    b'6PXx0Yvj0+j10Q8/HJ2+kBYnXldm2bgrxTSW9EK0NalmN/5tzQI4XFxjPt14uTZqK7ClhWO7z5LeYzlblvKhL6Bnk9H4gC3y7Gpr'
    b'kefvUHq7zMFIa7U0HoaSSgLjMX62ZNv42+4T+dve0yWLS64Ci4tXQcJSMsd4xN7KhwJZa0q5wFvQTZccnuZkZIAv4ZucYYzXLZBf'
    b'YEhlAcV4qtbzWCjbG6/YG7hWYCC0tI9gSVeLOo3ueFxGN2mW8ZKuwgN2wyHiBE/YZMEzlA3iHHdhZjS/vafysmz56TvjRaHk1gc0'
    b'HoD4FBWp/9cDQiELzgVCYuKwt2DYbFWgFVvF+ie/vDhaD2ibHf3ywxu2zX78WV7QinVgrOBllVY1B/EdWcftPlkegJQyzeLyjs0W'
    b'8RXrj8kwi9bjO7YzGu+zo5MX6zuX2AFt9nagjUIT+LS/MxRpw40hBX9+WpWwvdksLZckAFF7j0NnaZV9Jc1GWn5ilmecFrPIC5Sd'
    b'xKxaVXWMZip6rdeDArX/nRz6eVMO9Oz76PWbkx+i12/e/BEjVwnqJPkf1heXP93QUqh08gIll0gOn00iOJaRPJYqN5/dVA7iTyar'
    b'ZbJX60Q+ijOS4igV+ZXo08MySJE1N1iNwxDH5C6AK1PywAtyS60rqvgkEfS76X6iNKR2d7F0mMcem1MDyV5jgNpC3gfMdBD8UR9+'
    b'olksSLM+bAlFn0EwJBnXWoxH7E/YsjrAM8i+Vmf7MbBZ8gMcXPjwVH6QFJBg9Oc8vk5BM5NnSCLrnE3jAsg5nkkgT1tVfbfgbJdG'
    b'QqcUZyvwFddSdA6avpDWj0xPRUURRKnFdgJB7j7pCHL3SVeQe087gtx72gJSwQRXv+i24tPoQ5Rn4NchDPIPdKwa6dtHf9k8Qq/X'
    b'e+5eN/kEnm4f8P4AT6AYfCcsDQ1Dvlbl+rAG86F/27FvJKQlMPS3YiWKO5FLwxOmA36WlJEdjSyWPEnjrB+Xntxky7hRLytG8aSC'
    b'6uC3zRNPeq2EZzlszHj05NnuU0DY+JYChvSXcUL2tn0AAs3Z17A34yEb8y33tQI/H0DIpXtj2wS+UU9nDhKBhbJiNF2kRf/DkG09'
    b'He0M2VNEAfKmuLUDDXmWScDTiKC0bFrB5cQBGYzqMs4qyFPfjz4YyBV9AJQd77JDE8fMw6b00aMdYw2o3e4TTztxotra7T31tBPH'
    b'xt/uEfseqNcBc8jJiJ29SwvS7FJYYkmTwCctPmF91CUacPZ3njDhvscwiGI+Y7FQ7nxVSZvTgTS+UHcfWl9IzoFAlcissWqel/WW'
    b'NFYlw1BkzCb51YrUK4IlxhVAMhyVMWRRt582gszKPTFXwqqn6K/chdaaSJjluntrmsv8Y1y9O6CrA5YQo/OQHkwwd7C287gCjnlB'
    b'8Z8xVjbBNQk2BfaB6ocWqW1o/bVdgJ/tRoWyXjZhrKXhEwmlI7XIb3h5SKdqVRS8PISzZczvJ83KItt6wJBtBcNMEihN8yxJgU5W'
    b'IMEfsh2Wg9HrTVpx8248l0/5ik3necUzQpgYEHNhYcEVz1Zpxl2OkcAoPv2KE49KrDTcimA0Pd7a3dl94nDk1pp5WXNPvCDrTAvu'
    b'3MaVL0UdeSMSN+6vI684Ys8NTPIEYer2nnfZrfb3fIhjbr7nIdrGOiaZZGo+gYk8+0p04jkz6KEQwNxOj/hO+G9GaRFhJTz7vll/'
    b'YdyB3gQnf4wqVwb0Srznt3efLLfhcSZlrhiQnfXrOb9jS2AZ1ct+ooS+ebECY5cExcnM/7wnDXXCZzyr0mtOLxI8Q1KcAYKVOLsD'
    b'ei/IPb7rKGcrUKXfs2/2nyq6Lok5nRuSyjybaCWamBD6wygWT7FmdtBb1XKTJZaNrDUFkwQdt8BWlXU10WmatxlWOiJwoTDT0Sru'
    b'L8LWwl4r7aaFtlKDi4S/oNPG6Ug1tDCSoK6EvQ6Uo4uyrIRfLP8+04DbWR7Lg17Assy3XeegNFPVGnsjCro4+ISrtvD/eq6yuS3A'
    b'DcKUkQv/ylo6lgaBWANtkrGGshTX4wgZgKETZHP5lepf9E3tKj4d782k+/8iBy9RYNniab2CX4Wlnb17vfHeTCwIcJt7T/Y3BbD3'
    b'ZL/nH7i3rRo7DXcou3VBSJJDs4/R0kkmXDA9DYPtjFRm/ub+QS8hAVVU8iuIBigpXRdXWGo+4dl0DvusDS02B4Jz5tfgPxwveFlv'
    b'BEK499L0MbcVib4j9PqyJ9/m6PpFwBpHu0sLUIYOt6F5sb1gfzk+PfrhWErSVaXH7Pz0GKLBH//40+ujc1+Fi94sL4F7JyKrFcsl'
    b'v04r1CfT1Wu0OTt+Ho33XnqgQcnLN6c/7j3Z95T+ePT89E10evzDqx99Q/n++OT5H348Ov1jdHr8+uj81S++Sq/h8/Evxyfn0dHr'
    b'49NzWcVM1CG2KNHhWXUQxtDD0OOsCE9gC+B1ym+8VpSN/AfKfSGpJQUS8eKJ51elIlOOx2rT6DNSUQgSKySBPImagily0M0c0+jD'
    b'sNGEoA0eNK+IO9QV6Tyo9OkiXxtKGY1KSWINENj6yqjjRqWR9Rru5L6z2WwGDgEk3YniVZLasWxUa+V2ohf20L/eOtKTPqY/SzcE'
    b'bWKt2eGZiJl1+NEAiJKur5xoCF+F0qpaPkV5AkZ3KTiB7Fyq298ArTmARgfIARhVzThdLpiNRihGZYRl+GqVvcvym+yrT2bCullP'
    b'dAFiCQolYvQ5cOrqCFYq+IgpKfxKiCa6LJvK1ixiQKttjICYORgjfIr8CDBkvedo/KGbaM8O0UY5pgzEfQ3vkkZHyzRLl6tlVMRV'
    b'RcyZt0Nrl5wVMxGz7SXZGLHom0HfDCIdNYduIjHtx0eSBzrcoHc0F1+1TvcrTV6/IvL6lfIFR5GFcMRG9yH3aSlxwEi8FM716l6h'
    b'bsbXcJ4m0UCElIsquLDzBSQjrtJkFYs8uHeGvJcI2J/dxEw+MXCv13vzGpKUEqwDRtwb22JFycEpkSfoL70qMyEnA7FewmV8K5Zm'
    b'6IgkhNB1acQ6uItIsHy3RrD8Z1EPhK6IYkC6p+/6F1kxyjNe9QHZ/jwYQLamiz9fTC/98HTczj+rFDK6ExKTYSdpNUuztOZ9HCDE'
    b'Ige59GLRN8twUIMhi2/T6nBsyRIQ1KhaLTGIBVzGOEDZ6YA9BgOs8U4j/7EjZN4BERjtuhWaB++6nM+G7OuIRrxIs3hxNVpUdfWe'
    b'RnaBg7gc0iKrv0qQjR2CokuDgo1kh2KV/2eErMpw32GLsJA2XRWqSKVivFjZGXFACA4RFeFm+BsNzJGOGHES4U9+CxE+2TH+k+ZZ'
    b'M0lb65LRuZCPAGAWydxQ4nTVT+yTEAizCFoY4dBAbhZbypFBAVUHpQKNu6uQ+f/+T4ank5oL/QzCPhXNwKWT/fv/9r+z6ZzHhXRS'
    b'KDh4LVyl1zwziWP1O5DeYfUl0E1+W5DYhWAeJSDZFO9nGKKaccSLof2hcj/MpjOdJh7jdeqBKxmVJvmQ1T0QKk1V8qRa6/ecYQH/'
    b'7gys8QmG5ppEJ5RjwYNEiQwDqPqwcJbUTxJnkiDSGgP6vPYw+o0hCBBXJa+qHBOTYnJoGTpoGl+V0YQCDvVm05kIHQR/XYHe0Akl'
    b'lPFa1qDH0ftVvEhrcAS4wvCDvTJPp1FcgEjCH4wI1zbKs4i/X0FLFVu5d0mDhS3ul8mQVdPBkIF9oZWgyuuzZmDYJbQBq7x3/E6w'
    b'77YsDyjqVVkAgX3mklG100hirsqC1tQXKdvY1g0q4+FYW72ZjEl5/6mVNoJJu9v72N4WmVUMurQSoJnh9yz4/2mW5c9ClXZVFhf2'
    b'FBq5k9RqtU0V1KrXQIJdgSB2tD7PySKHgGkoOCJAo/erOKvTBYf7ZX8w9BZ86yhjZGcmHKHgAvCKjVSFQgdupvcBwssxPVPP2Xt7'
    b'xneKrBmzheWUrddNuRU7PCwldDikKbaZu65FOmumVaeZVoGZVhvOtOo602qjmVZdZgonpctc9WXhzlZB6Dxf/+n0zhiqbjLn8MHH'
    b'+slF45qHchM5XJ2226RymlTrmyCbYDXCYbrNNJtgsYl0GcHb8B7s4dnRD8esf0ZM4lESF8gk/oAB/kRA74GhmsRuRl80mTax2ibP'
    b'KH5A0flsa7KavuO14EbZIp6IVMWiyZVw/9BNxBDgzcL6gom9Qp2eMCgjC7OBCeW6AeUXxe0SILnAW3Bv2Y3fNxr/K11qounL5y+H'
    b'7PTNq+dDdvb98yFL0sUKIFtApg0gz03jUIKkjJgfMykArmwocr0FNICzM9rb/wFNLHb3fxH//iv+O95/LndVssBJMGNw3+JdJCsj'
    b'll/9fe38/d75e+r+bQ94Y5Y3ubBZKkMTYnyPEG2qvtg3eOy1PpXE7USihg9wex2AH3fIhExaOiEbqszXIjJfiz5Ekzsxjn6C16rD'
    b'B5q9rT67N9GHCfQG/er6X4MAOGgHV+cgijr0vzMFx64JJVlrRpW0H+zQBDDpZsjQyx1HYm+1lE3Y90DVMfESjf7xIbtpBPz0gQgZ'
    b'IhnTErBIzuHP2SV2ok+dbxutRyVHT/X+jorEZHeKMARNO2xgMZXeUGANdigqjtIqzfoXvbN8Vt/EdIjO+DIFcceKGgqZHE9k/BfZ'
    b'xSHr/ciTcz6d01GfoVrWrfI9xfyhKjzjnirHGS+v7nrS7MIgtvjlSoZ4FaI+RCmJgGrh+jujJztDPFuN153pGN4H0x5RrwTF4IpL'
    b'+OC+vHAr78rKvGgBOZa18unMU4vW8CqqbtYNvVwteJTPoic7jVHvd5vd7n7rgOVQyNrUN5b9TTt6gGWUo5qlWWiFdG/BN/R9V6zb'
    b'2HjG1+2ef/d/mw0Usozm6TDfflQNeUxx9i/h8AMmWh/dyvK4w+WHuGJ/davLo0/VZ2lmf3WrSzJA1XnmfLVuYckNUF0E0SB6jxzW'
    b'Cj9eyxVq3TGXwQ7tmctVh/bMI3Gz9u06oqS8gXFhf6sPff1O8Q0IKogHqoe0bREAoeQvuHMg5TiImzsU62QijSiz9pD9VRFv28IS'
    b'1hLutCYyWE2UOa5cgGBVY5ASByQHCD3LwXmQwGSRST7XhgLqFjAEf6FdbUgDQxTEFABadbaANZbnfzKNajCMQbLZrCeBSaY+KngW'
    b'L2oXld63UEtwHNuUWuo5xCL8pmeWWzQyPqlhCgSzMa4OlDK4UMaZ67AxtoTVHYdE8fcNFBdlDeL1PkC8zPrmOXi/hnrJtwrVDWJu'
    b'412G3+X7bQ2pAKPNp36UlMV74eKSGP689MBAjMVKtmmQj/lBmhSXGfp2jxNnL+R6yLcaPqra1kM84ezGzsPOJUR7++zr5r2hKtAz'
    b'1ahyvb7Ke2+VsVlFTYmm25xOQFKiX4nSmC6ZOZplMOU5YG9QeRcvLsyUZjB3VEf6hSqY0XxmYnzSku/AKAtIxUD1kWYQ8AIOGihP'
    b'qaknyS8YUNjVe3boWEH3qk6QzMoOHGC2uoAQ9ZzW07jgt53aq5oOBDf9xFpAnnwVnnWx2Oiu62Pz3jZcOJVpdlVtBtjbyt0Bk/qu'
    b'3wdHG2ZCiquK19VaEFRNt/W8iZUMR0rwAaiNvdvmYVAURle3ENRbGW4mWVui4ZZGKaOaEDbTg1w3a0IlFqMo81lad1pOt0FzbzY4'
    b'sFZtB1JyYfE/Itduh7HJ+nq73GwQjUlvW4vv217rTrFRav24AijYGJe9eBsPCix4IEde9wVrtgkPrjlvu/+rAlgzOiod16XRZKMt'
    b'o3b2IDQT6T2ARpMEUn5CKHi4JcHOLnQOjTaCl6V404esvxnVYFtrlmORxpN0kdYpN1ppYqNZDlnozl2lHFpPv1Xd8JI3Vs+cvt31'
    b'JM/fwVYKBwo9CmvFLOoTwmegV+4bcv18Gk26AfV+lwuxZnevI93U2K7fqr8H7kwz0uPRDu2MvLlkzmHzMvuOCfGy6pJf40tsktZJ'
    b'3HmbPI0aGxUAHCjpvFlmY88KFvyq8yx03cbgbTD2h85DhTZAlvO147xPB0HoLutVoLio7+fjvmbjHbSoJVzxV1JY03Hg5l3jQelt'
    b'3xDX3otJep0m4PGLqeuKLtdio0ljn2WN6C7lC0yKtwFYo5HD2lMmprUMPaV6a2VHVSbZNchwux6MXo0CxuZdUrmDoaX5msn0saEd'
    b'MXsxFkNdtuZDcpsVt2YdJVwCBQ9+kuMxgaj5gSFyms2GbIt+uXQOQiiXpsc0EtLoCc1S4suWafoKVHUJKUYhnFHV70FLFQ6xN2TT'
    b'uOLC8YVlsWk3LvtR2LHhpBQQd7VQgCRnAHuge7GL7NW0y7SgxYGOu+p+JEJTqEe4y2I0hrgWJ6Wy18LSr/0dF/FdvqojTnhsNtiW'
    b'gwqeJbOp/kOQv76cElA8MkBXlueiaOCFl4HdmjuZbWdd1owJYajfxYiclf2O+dvOpjPvAMxX45ruCYT+Q3MP+t0Z6N5eSpnEUM5E'
    b'caQatrex7NDYT1Ma1uzcJFICNl2IKKLCDxLJiIjZVM8kbGYMDKWCp3IpREUGa4v1NbQtsALZG2DsHAhiQ3/ZkGQwjbEEKgbagBqe'
    b'C3TzZN/sZm9/027MP/XGBnocTXh9w3lGthPj0S7E2NEGX+l1hHJUotP91g1Dv2y1Yo1SX9QLMRYz/0fLUGVmxiYc2j30RyQrCBUc'
    b'FTzBNbx8kU7vokbtcJQyWP8m/hEYLVnOCrHOimw3JgYIbcif90EsbOIcyIqfwEdz93SL5gSt5o78PDxSwzsuWM01obF28msLJ6Q4'
    b'Cvi6alWABzM8xnNXB2E7+Pcb4lCIkLKz7+ysHfK175V5YsOn7Q2DfO5o51l7S1to2aVFQ1jeZkRKEIMAL/Wv0mXBozeQx5QSVnnR'
    b'XswbrBCpWhu+jwW+y8YlX/BrDNV/SKebOnosqZn6BLhho8JawrUOVe2lDKJrm30VIawzFckx9qW8x+IUKR9c3xLt2BU0L0myElia'
    b'xnAFaN++bzUnZ3bmS/cbutDlMtpaVu/6relCCYu+aJoi+3swBFogmzI5+nWaiKCm2dFzOGCtv7s9nRt9YZQQ5/XwAP3E15Hb1W/Q'
    b'i0cGqGWJLR5Dbm/YBl9yJa8wzNd6sm1Jtr13sU0MHYa4QwuL3nZp0MDxsC/GvcBVDwuu7TJYB7D7bSCdvjbY2g1VaV02f3OpeRew'
    b'jbfmg62avl08y3ZhMj3DBnd3OZTQO949jc7a2Va7UtvtvbOnxMuGu70C4DOG6O+MvtmnizzQ3dcWpWhaQLgIZ9QITtRYGqvZWp4B'
    b'Y39AXJEVCgQoTixMNjJKemYciF4v4PnZCA1hdiDSptnm5WD4tM4N1W1v/S3eCX8zxjri7/u9ZVxP5zyJspysk+ANtrf/AAAhMByK'
    b'7GRqSIL9zYPCBriA9wT72UPCBpDjkUxPjZFasEuKnLdWxQR44TQSwYQ78KbmESq5pFl3AZMifNKtO3hwZvbAttFeHGUp5Iy125HA'
    b'wFVSur7xfW49i7rQYO976vPvhLA68PNhe7Q/D3dzyEePEL+sW/Y2z5mm3Y8zzQ6N0Qx8794t9zdr6Tfo3wCA33jIgSBi/rYCEjHv'
    b'Sl6tFnUlzQ/vxQpcgCFXCgeYz2bpNOWZ9TL9rB1us7LdZN215e0GrTzWE/dYaTBjytJI+s4/eX+/Zbac48zYZYnfb06kDLS9giB6'
    b'wU1ekrNB32o3hIhz529Oox8gut3LVydHJ89fHb2O/nj865/enL44k6Z08YLMWe4J+PT46HV0dHZ2fN6ATCqle8M9e/Pz6fNjByqt'
    b'Qhov5Pr/p0ZI6ZqwQROv3UoDi9GBoBVO8IjfC5kNNHqgfdFuHRssjl9G9tDL+9nrCj9b7RNx3AbutyfiAP5H7ogQIWzSxPFU+A3W'
    b'/u9I5QUb9lB70HWGv9ECh1Dgt0dmkEbRZREnf1lVNU/U1mjOxFlsaih9VNTlCVi5FlTjnmmAESbO+N25RTv10CSZPlB2L8aN2rEP'
    b'mwQ0wYhgSpiMCaNKHLDWqBIUSqKC6jSyhs+/iGghzMuNyLmfi/v3uCzvQX3uh+JNH8JNWuv32f06rZqtu58shTWdFZi/EXGRA6Es'
    b'A5uTtX+cm/cqLiGHbDYDZgSFEVqKpmBkBURRhjig/TVi83Y5jEeW7g1O6ahqUez5tVd4shaA8astDtQLpNsNu0lxYM1cd1kYoCle'
    b'sGSv6MNmkBdbMAv3u4PZNA72NXnua5MDZ7e0dwB817T0Js2qvEw/8D4UoBRtLGalEzT53NgwC2VkBWQFAfcBg+Cm7K/MdFYLOKlR'
    b'Fro6h2xv0FaKA+s5vByvgFGF33URZoGlfJx7BzQCSFYiBsFwEGw0gjSvWF+aAULmORyuGyxWg+4ej1rFz1UmioEAjrKiFd+39wKr'
    b'eIq1YtYYtqpUcsir0xd1Dz8SnING559oWLKdL1S5GyE9XDfgDJjOWuArERzFcT08ZDtGnJk4rTg7XWXQ8THAduIYO4E/i7jEDIuz'
    b'OIV0OGnmQ7tRI46xDnKHwaUh7/XhRzNmYGNr0hn7CupiBO3pCA90f3DZCE3s2xo7YYnIOIJvcDcTGVAiUJ8m/LYPeUiM/Ix6QeXc'
    b'Hmy7dAOeQe5nE/BJfO7iSzReuoYAZulea+nT1lLITdhSLFPwhHpuAocNRTELRZMaY5DNPfw/JhjsUTbEnkhv46S2UcBnvTL6iHA+'
    b'kdQmgru6fZ1MX2fPqOohu7IwTUbw1AgCeNMI0Ymm4pg0pLiVFMcIDwQpBW4xwRvoB/OSFbdudC0rVqT8cAWU9spCVRd9dCcaTSrM'
    b'KYLsGJF/44NcosrglZ3K8DfVcZgB406l0XmQ2aphs2ri8hjVcQm3xHgZQdqjYVudvQ51nnaoA2nE1laCPGLrR+Ttzpi33hCFRBgr'
    b'8EpqKd3zbOzbiDZ5LQR12p2du4Cc9s0lHlx2B7zXCfDe5oCfdgL8dHPAkjytW4vdzUFL0rYGtEScjda523rs3WdBlj5y2CAAD4Is'
    b'9+rpXthzr57uh073W7774de9+ronwt1vszZeQ/eOldeM8d24YorbId4k8RTi3fMEOC6jI4N1i+s6ns6NBFPO2bFyQ2l+nx4tc1D7'
    b'qBGLdHLValLx+tDoHCQZJifnYwgR4ATT+U7n7y7+1u/DP8YE2O+pxGEKwbOFqjrMoqze6GlAEjcRAHwSJ2inbGcUmfUu/nR0enLJ'
    b'fnp1DnH0p+/YLF9lCfso23yCLPBFOk3zVYWJZ3/HYP4FsOj1nC/h4eXuqbtYfXpbT2IVzNHdHbnLQvdblGlewoNXhkmRVY2cZebe'
    b'tufssl9vnl6bYVna+5PtKNlZmtW8hAzleaYzja3tU6hlYpBNxhu2pdxmbpK19V3msdADbdAoucviZTqNFjxOeFnN02KDxphjNlrw'
    b'a77QCd2kscz65tMyrVIVq2iW1uubVDVkUrm6iyaLFS/KNKs33VPISpqkS8gOgTK1IsXck0IaHBwApMAKpsfBfFi+ATxiJNoYP2H9'
    b'3Z3dp1s7T7Z29wcHbH43KdOExYtiHmP43aLMITonBIu6SUsO+T4xpihEJBagjq4wKj5IuqtpDBlVmUjqxdKsztl//7//j//+v/5f'
    b'7MfXWnrC6xF7Uya8ZEtMuiskEo9YWUVAkhYYoiLP2KriFXzU9PPrJevLxKdi8RIWT/JrPhiyP4y3//BUgFpVnJVVOn7CHjOSfLPH'
    b'mFz1a/jFds3oQ2biNGPWY18I6R6xM8i0x3ZpMBkkMNvfvYnm6RX5Sz9mp2ev2GMr7ccQiRSPMCMuaCoSuhkeyTSqS76cEF5Trlas'
    b'Xo3u4uWCUoPA8wsaR2klM+j2e/hl/CSibYpwm3pDqbahN75XuCPRzFlfQi8HuwJN5+MIjD6qfGGl8+vY+KlzojdpjJkOd7F3flvL'
    b'EHXd2hrbECIg3VInO6venjl5/CT6w6/fn756ER29/ukPR+HEyVt2LmR1KuVJaUuJTJl2x09kpl1vzyKDof1mV6IF2dzJRnyGudZP'
    b'zyCFeyEpxP7WeG9wwKpikdaUjX0b8jyz0zOKk57xrK7YY5moHSS9OQkpHrEpzGuL39ZE3pjYQtb/6fX56farNyf/yqr6bsGB3NSk'
    b'VhiMQHhXsXhW81ItjIBHaeOXPBLdwM29jMs7EFcYSZBBODIHYW25mtarMl5skTCc8VuQZKR51nLWcB5wYGARNj1k1BjzYHspeAjT'
    b'sZlap6hMq3cBfF+Ltdb4g+h69oc3p+fR6Vl0fnr0U2c8rSwEWYukVVlJJLX7W4Odop2DnQIX9reOjMvr2eCATe+mC75F9AU0t9MV'
    b'+EUe/wS50SioIJvGdby4q2ra90eEYkcvz49P9dmb8GkMlweCi0qOGfnuiPrH2Z0MSAR3XDRbpAUY9gtwfQLyLXu+hznmyRVMZL1m'
    b'2/jbnvzlqXGTGeI7kUf7EXqnq4HflHFRWZ9ElITGXTghtf2jtly8dOe8TLNsvprI5xSuFK/qdIlinXW30H5kL9BGR8RuusllYC1B'
    b'qJ2BJN8fgMHx4m4Lu2RpNhM5PFnCgdTkpUVoTPAGOIUTeZY8ofvctxn9VcUTRlFnIRMoqGfquZaN0qYAt8QTMgQA2SzLkRVKK1bz'
    b'6TxLp/FiccfgQSHZI1In4N4ZsLS6kb3KEl7wLOFZzer86mrBAW5as2mcsQlnR9vff5Wwihcx8KkLQ4b7yLq39r+Pjo9OX/8avTp5'
    b'+fr4+fmrNycGUQAawCsG1hKsnqeVTIshYbVhywSe0ou7SG9AGGFCW48ACHU0mCASNLOhNKgkUcrgCA2qCbywRQJ7TUBt4zOIo00g'
    b'LYrXCqLn5pIwsPy5QwpJPmvZswAzzssMLWQrByubLPxXFdD2BHLEl4DR1TQtFmC+0m/c4lqM/Ag54Q95xiEb7pJVNxxynxR5PWTX'
    b'gL14gFT42cGIiXS38QIXGB7UqSGsecTqnHGkvuAigjlFUZ1KJwvxEKgbTjfl1QgeGTfx4t2WIGkGJEg8nOG8RaKD37GKS1KwyK/S'
    b'KZ6VeFHleL7VKe6G3tPIWvLNcbu5YR6UDjReLiJFOaL4quSUM7kNyiP20/jbxz/t7hywajXZSrNkVdXlHXBzZZy9Y49ZmlUpkKXp'
    b'AoyjSjbJ86peN5JqNYkkLOSDNpuI6DMSfUbY54MdcGePNj3dniO1zdqWHnLGNuF4l4hts5a5dyUezREKmrEfaNE2+jVNvdNY06Zl'
    b'ihZx6/giczmQNW+y/ej5r89fg2E85rT/ddNX2f4mr7J9+1W23/U5tt9geMNCPHwytcjjbH75G3a9x2D9p3EpZ1KN2PmcI18j7EZA'
    b'OrMqZ/EUbSAEBEssso37lUDq12JVE2siLo1qyP6Sr+COYXEGfHZaDZEDnq2gvZQXbX/PgJRT53fYJ6ZGLJCDSYDovzh+efTz6/Po'
    b'5fHR+c+nx2ewkshxwCV2RcILAQ5yQCMXBaR9uipL4IEMsRXkE19sa1o/4fP4Os2R30IOqrzmCRF5H12+LRY5cniL9B1fpPM8F6Z1'
    b'HQV7Ynswk300XcRVlc5SXjrkTO3SsyndVDzBrF9snufvRuwk38oLtsoWvKpYbPBx+LLhNyAC0375j+Dxw+NyOt+OV3WuTFgAIImY'
    b'GL9Nq5rMhOYxuQHz2yItIVX00arOl4Z8D8cD5wDux6LMi7zitBlxWafwsGCTFXKauIswDswqLR5ZDYE5Hd5nUxoPmArOwFDLRdx3'
    b'nINVGbr2QLw0I1JgOq1H8IKBzKP9Ncp7ZQTRLDmJl9z3XSYJa5a4wd48Vabpu/GOr6DgZZonvhKtyGmWkQdqsCkWr20fHi21r/IZ'
    b'XBtl7V8nW7kUuhlDpW4WWU8Nj/bXW22vW7Wm0tDf6W63eh6Fp390nfpFSXbUccqy8t4mlTcbxu4mtbsthRp195GgaB/MR2tknttq'
    b'hZGZzCpCexjctDXLs2Y91iyAlxLc+r7mBc8if5EIghk6v0IDSVQCxeTxYrGutiQaa+uTS3kZ30CYppvoyftoml+jefuaJobHfKAe'
    b'1JiudGyBCMQnrbVlpID1NbvDVDXB+wKsBoK1lWfjepKrq64h3v8/e++2HLeVJQq+8yt2p6ZspJRM8SKpbJbT0TRN24qSRQ0lVbkO'
    b'h4MCASSJIhJIA0herGI/dszjiXmfiPmJ+aHzfD5iYq217xckSEld3SeKEVVWYu+99n3tdV+5grmueyNARV8dsFcIQTKUuHg7fbVQ'
    b'ZkhVkzIHUXaopiSsDA2kzuaLnJl9bTlFe99ma+urZCrw94QdHB0fxj+8f/39/s+Hr9/tvxIEuVXNrPGnw+P9Hw8DVQ+Ofn5zfPjT'
    b'4eu3L/9kg+5tCOYqggy3ivYP3r3ffxW/OX55dPzy3V8CAN4eHsTbuz/0lP5wdPzz7rPngRpvXr56tX8cv8U18Vf5ef/g+Cg+Pvzx'
    b'5c/9VV6+fnd4vE/yQn+9V/vvDt++i49ev/pL/Pblj6+Da48M00788vX379++O/5LX63n8avD/e8Pj+NX+z/+uH/8fV/dbZMD81X5'
    b'6rv41dHrH+NXR0d//G7/4I99db+OD3bjd++PX+8fH71/3d/zdvzz+1fvXn63/+OPh8e9Nf3KO3tnfSoUz+4f/unl94evD0Ibd/ju'
    b'h/ino1ffv3z949u1dUXxD+/fhrfYy+p66/w+PvzlzaujtbB+L87e23fg0t53YLbidz8d/nwYvzl69fKg99TsbMdv3/0FBQE95/pk'
    b'RNLIjLMpab2qIGbzaIki+So+K+v0kqyvuPVHkWJohKQBUyYDHQKPqiV2Ej2gSaywYBUGpxOdRtR/UR1F5WkA9fDn0vNAMlBK2gCB'
    b'n0I+IwGZRGpbnAM/JktlH6d6AijBze4wKVdc5F2SJV0CXHfbNUV1vgkeThmLZBUQgXF5Elqws6ccWLs6EyVcoQaC39dH70CzMa+b'
    b'NN9M6+oqb0D91dUilgs7u2UXYGrXJlXRFb9xRcUj9pb/JhULiA1ECzFsIQ6JmlYJuR5P2BnQMyB+PvrydV6UikHmNkpCpyPbQBii'
    b'ohI2DyBZ1QqbmptgkbkMV/yRtGonfv3+58PjlwfieLKZxtxq/iXr0KW+5dFI9A0nyVxtPMdqobl53anac2MpFdc916zK176ugVdv'
    b'/YsXfu36X7o1r9yT0Gpv3PelWfPKDH1hBr4uw16Wga/KuhdlHWIfgtSf2B6w9gEegL7Nk+y1/4BDLArQYY+U9WUuKyhB7enwwQ14'
    b'MHBw/zJjI59slohnf88jQ0Ao08sPfHwsUIH3hPOxkhGWjO/gp0avSaAMFthieSXHqrmYgJ/nbDvffsbdWTliGeI16KsVcECDquu8'
    b'2tw6IWDiFJyALJ+r4NFMsNW9+dK6nEJIc8D10ciWeIxP1cM6b+k5dQeUhsZAjlkwf/DAhbQZT5VADuXxMjTB39q6Go2n5F7a5Tea'
    b'xBSKptlqsbTEpR88IpH6uh3tgZw9Alvseatn4FS15HagDyZv4Nso00nTB0vMxoZk7tF6OLTwOhQaEPodiebs73To0GfI+fhC+9jT'
    b'E51uZ8AyzdXaoWrOwRm41rarxSIB12jlNkxiLlh/31Q5PYE2TigUQZmOgNY10XneJV3XkHtBb30oVibsRsLVQH9yjFwJPtoD5XDZ'
    b'26fTZsJQMb6+NzSs105l7CnW4nHAivGFDyZ10e4vxT01B3Fn/gTfgaqb7djucgLjwF1eJs2vq7wTt9W4oL47Sys+5c1kgFEtAwxd'
    b'YzR9BYFb3sA/CAvoaQLAb0T+tPqdeIm0QSKK4Gty+glIsl6pwhCJwn9Csu0VSH8O/3T4+l28/+rw+J2oor92ruP/0I3V9w8jlcRA'
    b'1ICb/sw6WF7o/LSl7dXIHQ+ZB37WQYW7CIxMqkO3NbumrfEeuDuwNxEqnMZP30TdEv6/LcdSJc9ezllb5vlVLo0BhBk/TrdF1X4L'
    b'+mKlYJQ5mVgF1kboadSyRdFiRAABGsF0jWY7h3yRUPSSWnMbgoCAgrKohXPXvOUOXtxw9wZEx+wQ/4NJuFv45jhIiRU4ZRpEHp7g'
    b'DwyE1jA4wOXA8+Ks9tiH/Ca904hcScIIQ6XteElWMEhNyk9dcpmTXav5ve1q0H+3ui+7TYsrbGrW0SkeYdnBI3vM242NjUds9in+'
    b'NtRh2WM/gxvNWXJ+njfszxAKmG1uMqV1B5u2AnXZT7RV/YQj2dU6Qwu6ogJTiYpdFHAVwM6GPb8Bh5SirbMcJAxCVb9QQ49FMVyM'
    b'8d7GI8bkqecLu//+AEIlP4P5LZv8KRoOgunGec4NW2li0FBt7lg0hIjdm2yZJ5eqNov+5//z//3P//f/4t47Y95aHAHsmVq/2IHW'
    b'3MZuEwoNKP/+300o3+fwb/ZEeA4VdbWnTBTEYfvQ5F1Tt0vShkxIqaxWc5LfFJ3+m265JGbupsvbjQ3JFh99f/jqbfz2/Xffvzxm'
    b'M3Wk0RqkHcmKh29evj36/vBtfHz4Cuqt3Y6R6oQbp8SHvxy8ev/9IZtxeloLzEEmBsqkgN1DAkN4y7U5kDYGyqZAtyHw2QzYdgKW'
    b'XYDXDsCr9zd0/a5uH9hf8E30qJe8iqc1iibBG0tBmWxmF3B/C73t7Zx78EH927mU41k/1dpDA3f5KSabBJRW6DHZxGAsl6kBwSsA'
    b'zgGXuWx5b26cmj2QIzcb+7hy/gy+wiAmUsK5xAjMHQgxL5NzTnwSL4XSlKWaY1saK6w90gqXKsBtXs43tQJ0iuXgP+4tmmzc8chQ'
    b'8Ngu5csrTeCwk2y+ZwSCghSLFbqGtiAc2qNMCWSvuLWBcaO61bLMT8xGQBactF1zyvn40Wj0FvWPYCKLLz9INUvw4+Pd46Mrl8bz'
    b'+DxVqzIdjUguJCTQM5bNp6TgjDEGWBsVVVqusnwG2R6rFbgNno7FizvtarSN4rxInmBmez3+kACsv9ghBAaydaiSTtsuaTou0eAx'
    b'4IjyhzWkJLHZ/AT7O50WLXK7GPGOxyKra/A055VPRKNvzC04Jbdscw6/EGiAYOgU5ISgRBEaixw6+uUkPZ0u8qyQI0BQRHtgIY8w'
    b'B9XBjDvjPPoiz8Yy94UR+wZbtV0WWe7r8PcbxFlD6Juia+gYUiCpZkYLfSiUueA3nqPvG/Z8YgDR6aRfJjhdcdopWA8/7eJRivDo'
    b'HiEtmZTG6VVH9lWdZDYNor1wkh6ZsmOKS0BRf4o5O3j7J0EJT8kw76e6qpuWOS/om/13P6HR7VXSAEnaXidL2LASYjJopJdMrR7l'
    b'0/OpPgw5p/hqB95aNmPbL3YVsXTVCqt69vw5V5eICwQcRVNkYGZYt9O8uiqauqLsHt6RAm4ZYYLWYsk3q8khqagEVMzVv/GI+GgG'
    b'bAhx994k3UUUIwsUxxh/qy6v8mgMPD7g16cAHmsXc7xkyykZYUbjHtJfTh22AVpRmISkYx+Wd39g7WXBQyLwxdVIf36EYB83vLDh'
    b'NEFb2Qc6hX0AVd8iF0yEwe9kmPUzm4IWLE7bq2j5UJaGR1nruK+FPk2XibFnks3B/LyBdxnQVFDQ668XELRCZaCHe6FpFQJgROjC'
    b'uROuQxGFzpiQkpOQx/y6457K667xFfS+hSIg0uM8b63Xjw4qsKHUCt60CZ7a08mGiUJU8X51q71772BA5FrEnjD1TIPTL3+bDfan'
    b'thzqOQLiHjVvk6u8JevsFg4CF52lSXqRx4uiTUenkjegWk8VdpKWx7gAdYOHw0QI6fw8rs/+5gn7+Ij9mHT5nsRV4pa3GCaSYxiu'
    b'jAUoAufMHDEndKDRKDoq4+yJEneSbG9soICAN5EBSXMl0kejYQ39ftB9FNdpFnwzxDBkVS3Qm3wMrHBvGBNTu8RVrZrLOIjDkZId'
    b'ZxP4d/lI6I+Tfqai3uM31kNyIrZC4YQkIuAOr9c3+WoFsQZRbOHLPjg0Iz+aB3VF/uoUbZBeyjfHwF1SZIs3R2/fxW/fH/8Inyhd'
    b'1/7P38X4+c3h/h+xopwtEewogpFkFA1uws4bfJ/ldttxA7UjBpL1mFN9ovgUIm7Svw15UzxhOQI+b5bTooN1uzZeOcREGM46X3ox'
    b'Oea3hKijR/N5m3cR+vy1szfHhyZVtazbLgzlSQCKXD8TWDbHmFB8pl8w7zFg385g6ONg+TczHNUYtSpi6bfVfkh+Cr5vfv2fa09A'
    b'HETLqT1HRhWMfoKrDNcG6gf2amfstsurTLQK7M222eoiT8ru4lZvGOhu1zkYmG42sINqFr0bKQbdf06WdavzybTf5tzP+wbjP729'
    b'A9PWxRwbuD8RQjKGWOXnxhB984GmxI/hP+EcbX59as+M+6QhZVW6J7nZ3nEzx86JChdiDxXJm6zKZEa8OY/SNQ7iWoq+v73DvmGb'
    b'kPBMl0moddfqQYLknS27Gp/EL/F8VZbEYaHsAN9Lv0Qhm3MEvQCSDE8X6CJ7SAGqhwkf4/wmWSxLzFW5uyVIAPTrXwdGPX0xNEBh'
    b'F4B5viXgZPkSs+MNhoMNRhP2ggMoVdbnQe2FOxikVQfSFTPZ89UxtSPATqRJh16eICuB4PgHSfcd/D6QAM367SXCn4KvedIQ4Sfa'
    b'vqrPC4iPfZyTt7oWocFoC1vY1ClUqc5F47ddUmVJk71NQc74QLaF9/BUzgo93gTp08+54EdBtxpEOFDZIDwWAlfQdKtDecevHAgA'
    b'iCWoqzwiY4e0LlHdD7KtRY7/RFIe6FTzoaBnQrYCoU1RRSdbE7bNgwPioZxjZW9Abe+CfEBecQ9IQYSdZzxYnyACtcXQFgRpYVlw'
    b'a6KsCdOGybPrFVVnRFjkg73lI/1G3su6YdEtjnxslw2cSlfXbJ5fM3FpWbSs29kHuF+8u/HdBFAqfYtuZzPR1/huPGS+IOIi5CPn'
    b'7MSpbPGYspl1biPIldBFv6heSnFJZp77YcVCpngNs1G5M5qwA0gdMCHimmdVnY34W2O7qyySG8Q/s52trS1wti2v8mY2Ks/m54CN'
    b'mqTK6gWZsM2e6YYSOFqay7Rrkqqd180i+mU8YbdqCumZnIKLHswpKCQ4QwQ6YQY6mpUNcEvL7mKG/2/OAjgEUEOj5HU2elWfkziZ'
    b'oZesvhDtbPSdfyXEVPM8g5myq7w5q9ucLDfsif9iTFPe/RM4aXjjDdAjWicw4MF/mB2PSigRu22VpWejPbmMVlnFscayFhY04hgH'
    b'Klb5ubCfMm6SVv9uY/014rrPh94efnOAN+JMLWqeasBkGh5UmgrSJHCp1dKtqGsyNBUDzyVYug2UugMs/IUefENn4IkbhabgBA8w'
    b'NJL6ETvkvKqUjoCre9oUHchg/4AsLI8mBex3zeUvQX5btDQYYmEQkJzVTbeG2X7E3uRNW/AwHvxhXBbpZUnIicQscVYA4vHIY9hT'
    b'5lWw0hIm8zxeXGZFEyk43NCk6C4Y+DdqJWATJW/EdHmJy3x9NhrDKzzXotTj8NB4MZL1J2yu0nSYL3RyBc7woiIIlj4YnX5pdPql'
    b'eK35WslCr8idAEV+KdowGRoK4kHnBoFty9tNcU2kvkibIxdr4avMJfBCuOXu3fJ+W+Yu/zrZtC2FNWg9tcNLkHm426hB4DsKKxvN'
    b'P16ADHCEGJFLsO/WUGK4tX12O59HwOqmpRmNRvtZxix1KHuqfdHkXPpnJXDl+tauBlkXQn05V8dJRkQ5OhaLtKokxToxjaKitmZZ'
    b'fQ0CqDxZKAMpusRDjKTGQ2Ww9apzpHOfw1hJV3vWq85vqVSvOmWm9F9O7luvOou5cOS+OuKSI1HVuexXf7reNbdwpBA9saq+dqkY'
    b'2NSghkKukWX81t+tR8DMz6wmXqZZw5mDQ6sbx7nXXS7NfXj9esWzoDxi+yUYLiFyk5JpqeaHYH8UVI1nQhMaM1gU0YfCsSgEkRye'
    b'PhRql9aLRV1Z2nsdGB7lohKsAz/JMto6Ku4RRnhBRQCjBOYFtpiSfDBXNbCUJvNyQr1J1kWxqXxPIk1qcJnfck5V8KyIEs39hxka'
    b'TcTNVWyz50FRfK6+3icmJCXzMt4txNkxikAWJ0Bin0754IEwO0uixYkgy08NBmZ8sgesswUoPSNA6ZkD6BdfC0Q8It4TpFLDsTyR'
    b'P9IzWX3tE7nGdFS8mHC0Pphroz2XhPzE/nGa2kCyOpmtKoZQskNoqybKnMePwzfW2sLC29XlFU0JnFXg5t6hAMKk6hANbPwr+J/i'
    b'zDfw/9nPgFu+W1VZyc9ghwLT2yVJUjjX0eYLSO/FGUP9bUehGW0oF1cJdWd/ZTSoEaFY95SFET2MdYveDsiB0SSS6hIYXP5YkLMF'
    b'm2lCBZ71AmwnPXKleZGXWSRSu1Ig2NsZVBsb8Bd51xSpZ9ADYGA+ARR1rl2vB0HTkuM9ZIZkLdg3NnuU68ASDYmPLD5R8Rmeoxg8'
    b'rQYxCNrh49wBtFJEPDdURd8RowduMo/eXgZRkXQX9yXbl8ktks8z8hCDfxOVQCYe6ETGSRetJxAdth1IRyIOgNbPUifZPWvftMlH'
    b'jx9zIH5WIKDmxuVHtPFMRLShVaI8jj07YH0j+By2EsiMwGF9tOfbDbNXuMz89iS0KZo/TpqgxesQOLzqND1b2BDSsh0KIS1bHwS4'
    b'4oMHkVSXGgxpaon8/aoqi+oSl3cP1896xY3TBYZ2/kMpjvuUw1u39RA/AT0GtIC3+Q2ywBe350UOcWmN+LfLZlXlDO0XnspYjpJX'
    b'AjZx4xHhYREQCe3NupotkkuIbpczsOSiwIaAdsGYZVGfwbenrF1iBOgLiG6bLJftdOMR+2FVlmxVYccZE6EOZIBBzn9AxMSnpnPM'
    b'Y+EFhu/Yz6+mG/Gb4/evwSrzDbhl//HwUAVKB+M5fCuk9PARe8nDZkE0Uh5lIWSGXt3LHJ2gGDbRZvhSwxbdtQVfbz/usW13Ix31'
    b'RDYK2LUrs/j+sE2hUE09oZl8EfVG6J4tTcYfMTIQBqLrKYNDOq/Loqaq8qdgFKWI0V8CgbfkTgjncCIgurpLSvWT0J9ZZV6nqzY+'
    b'qysZMUrvBgzYJUx6E3EjAVnAgG7g/2VYMisM2Qgz5MA8eQwU+W8hahTx9I2cMlFSXie3LcoWMOwuWJ8Dpthibb3IWbOqOD808uYq'
    b'ga4CmUjEwAK5RkiM68skIhrquUKQEQcX/MaNLeDUWCQibJuKtvp0+yvUK0A+AmKsNBpmyv4I88e5X1/kEHa63ER2tqVz8kim0gGb'
    b'bIzEvSlCq/6tPmsxFmcDAUCBE2BthzjKQGisTS/yRcIFMiqOKd1AuSRaATjYeL5XQFrqC6xHLNCcMYZEMOBn0A6hY67d83VnhUd5'
    b'BYcnSNsrnBZ8SQVwKk7KAImN+sKty6yXZkRl3rQ3dLKFJ1V8ZHF3egIhm4uBqSRUVCFjTfi0QzkpcBNkmUh6DrCUZcKzX+WeQHdf'
    b'x+kuZlgwauHLUcSoPqsSMB0CgkdrSp0HIKNJm4zSRme0dfcWMyec3aqg7Hx2/cHe7h1/bmDMOc3BZFVhFGDwLxIpvWzXkrB09/um'
    b'XrL9V682Xyev2RN1zSUlAoKeMk/gpoOJN3XEDe0BR7QqctITBhIRHOFTwtYSTJOfJ02G0YHrOYOQ/eCPC0EhEBCMQopONmUrdETg'
    b'8fURj6JELnnNon/7+vdQC014FV3FRzfuBVTVFU6WAOZwd1q2xSJFhS3LJM3B/yNvlL4bJfc4TXpaIVJ/Aua9WfVlJ3P6TBi6DLR5'
    b'ur07jx8T7tze/UGCSetSPL1ogZBnXKbxhhNi2jLASPlmIDvTtcIjAXzYwDK4AKzaMoj8zNJlEd/WEC4q6UCPp2Rs+XlBOVPKWxkY'
    b'a/MavAYAdxcVSIwwTXJ+o62dCohVsTDBZ0jTiznYm2qGutncNtGV5uckjGvqpSZfANkiD+gk5IvZ3JWICzljDxnanwEaoqSguUmq'
    b'pF2P2PaY7Zclng1MLAdyyOuk7VQ7HkuFuxMlZWmzDDCfKYUJj9Jx/yAesR3qELc4Av1sUZ2X+SYeTPw6NuP+6wdTgqnqqkpAKgsj'
    b'41a+BkMMcieq5DOYuc+IHcFktVo41nTUVcBCThtWtVrIMCS4kngYIwSJKn3P8vYMOMyaSfZMdFx3dO4CZ9J0kIj46ZvBD5CqxBTy'
    b'AQLzQ+yGP0JwisNf9g9kQAXlZcvj3ZoJVQWaJwSZh4ohnG1ve6iwDgYk50oyyEISrEOB7+2P/qrGVxUiwX6SYKUgYSmIkUCYxR03'
    b'H/A4HeeL+irnwfk3+caQ1TnhY8xLhJSl5Bq0V6qdfibEREGWfKgJ/CMhuk1al5oFVH2NllLpFP9lXk/TfIiqAm5bd8xMMX1DLQ23'
    b'SOFba909WbcnJNTABlLpFSfd4Eag1i7zQb1Y59Bp0OTTBcRQiJrR/9nE/0f25GSR3Z7+b6MJgVL116Ppj0cMcPTBuCP2i9+k3ifq'
    b'1cNDGTHKQhOnHUMqJnXPns+UwxES8yZNfr4Hsmj6lZZz7ZfEAOfuR7NmetYYv1Kz7FL76VUJUJHQU8ZZnhLHk666ej7XJgRSc26S'
    b'oCR3xVzYHGr3uMnPXS2tpnXjfgD9Ylg6AUDv+IxeNYmrsS9g7AZeweZXzQYtbC43spZHxKeyPuuwjAtHjNKyLov0drTHXu1/d/gq'
    b'3v/T/stX+9+9fAXhKSlKodY+tOqjPQsDLbPpu2KRt12yWEahVuMp4IloPC3aGqjHRDhHi7+Cewd62sJ+wVXDLYQ3X/o6B3szQKOn'
    b'qyGz19dptcTMv4CQ9phwmJpW9bUxWPgIyqgZCBrrKmtHOoymyM4hTJll/ZjWOSzXCZmi34zxLbhBF/blNGmTpklupQ1Ggx4N0CQe'
    b'TdjJ6XjC0Ft+hq3H0qVcC0CInaC6HmiYEff/tyDKcgALLuG60aN+XupzkuvDSukBuPht51P0l3oak0El6r/dHbxIWjI8Kedy0mNP'
    b'iTZ43U0o75ITMWCP1emgdU9LeI3zeXyydfrgpbbgqeGaEE+2Th1T02KuIdLgAqkqgXUyKvQtl7GPD100cbQ8w/o0ZzY0HffoWovY'
    b'd8pUlf5FXH/mzOP+0FVU3X3SE6iBvc9BTJruhHSDp3qkTS3AJhROZNBAZfiVnjX6mmtE7VkzRcoGn7oI6FvsRSgPTzkMMyuaoY+z'
    b'6qsu01CXabBL0Dbep0uqr83yMjjNy/A8Qedwr4lSA10P/zkJwwHGvfeghTg1rJ+leyruoZWptdeBOcr7YUp1PjQiu0CdjSZrFlmG'
    b'mGsMoY595FkvYAUzTG4h5CDFFQbPf+O6FHPdRIHuI9onaMSNYUAgzkiM7E7e2hRS5CNewTyT1wJCCKlzy/lqNBodQYj5JgdTwYS6'
    b'23ymohfMwYBJJSrPb+AjZjQVsBmNQGe1LRMMbX7O8igToc+z/Aq+XEJOhTpO9ar3IK0ccvzEGGEhuMYmBABQxB+UK1rjHAOXI8q0'
    b'fvqWUpix65S8DXZaASUMqXbJj86orPejV+SHEokOYScXgyAGjUuiX/YwD0OG79fEy1BNQEWAxmsYyw6pFzyTqiG3d4EisFUUu3KZ'
    b'307Yh7vxusvzgZ5BeIkpL4R4TxEibTA+6x4Kh/ZCPLbS61RrqV5sTsKI7ftlWmXFAg7nDuzYL9P2IlnmJ9uniIjyKoI+3U2rllM0'
    b'Z41EA5t20Df0F/avNC/IfcvHId8XIGFiw6LzY3aGk0TeraEya2/W7ouOZy0EQQBDKGLYErn7TVAftOF603/MjkMAL+92i8JqOYWY'
    b'btFvE7b5bAv8JOH/jeOyPd1iT1kE/3kC9fObZbT5G3hCbwQRKOw9Inkpe6vPQC1FyserndFGTLkYCMKfD1/++NM7EHkT8RKNKCgg'
    b't/c8K0GkuL0Q3HU02nWLd7XiF27xCyweb8Q/vMdQcMGOKWQhp5rNAexoXfDAg756UKRG+iJYb9ce03fHh/t/PHr/Ln777ujgj/FP'
    b'R8cv/9sRagLkuHi32NRt993h64Offt4/ttoajbhwPW8AObsPpCNWx6yve4ZjUI+TT9cl6YV43zEA4wIoJrDagneLFMFgob2ZljVo'
    b'wskhVjyVXCG8z3CFwO8JFwwIbSHvpWQ2qBAlRazQxMNXrsgAR8T0EkHxxBnod4hHEDK//hlb34DnvDjloKVqirMVjBH8QS5y3vdE'
    b'ppBHogljEYscjRI6JurBlOpnudbPuwupdbgu0MqFYBIlkWUF0dlIOf26KsBegOaE40dmVPVVVMtVR+YDqwqkTbI1gju7ZUXXYuae'
    b'S3A6QmOoiW56Q4vKFwkWBBAIDJLs9yA6ZsvIpK6pr0kzkgPG0GMcsbN8DiGuoC9uf4Nq5aJbYXRN3HMk8kWyYUHRgfUt6jqkHxSa'
    b'32EAE4ndohFGOB1NmA9BcHk0eN1M+VWiXeQqLF0UEPE7B6B8d16HZd5OL0jlubVs8nlxM+HriMboE2a0ofgzMDeNKxTHd6YFBgGn'
    b'XxkWhKKCCCQOxLUSWIpLZBnTS0iaZgmrk7OaV/MkpoE7JWcBAg8YtjYpJxC2EzvDaD0eQ8SWramlGPZqgOGPDNpIhT4fNfEHHNCd'
    b'maEc0KRTxVYzGS00xVoku5gIQB5FMCnjhQNOFg7xrS2sVProe8SBqXnp4PAui9n098ODAFnU/wlvHArQpf+pyhDlqMo8G8IP4xdO'
    b'EJsTOX5PTzKPyBcAVvxywNunVSwXtGkwcH4k9oNbrWjrZ96kb/0ninSS5hESekrvQVKN9CNlNek9WPbhsoYwMcF7Dtq9D9uQA8eB'
    b'2uvhHD1z7uv7lvV9R9EANuRAwp/dDLxNxQdvA/2Qmrol/c8+vtZK9BziIMgv1MB66/q/hg6/gsmvgHletIsAXDy+McBQi1fM3KZH'
    b'aL4f83eLaAv+fLVAIoBVWd7mgj5pYccFZUBm0hY4kns32eZF0UnfxJQsGS2jOyQBVw1YMQI9YQHiLkcQOwXGUMB7WV/lFXBogkxC'
    b'g8gliBLSYpl04FwqiSxtSBpVKqRDDqonegMMHfppaPeUD3p/HvYGPegd+pzo4aPfpE/zLg16m/4D3qePe6P6j53Lgq07emvfrU/1'
    b'Yv3zGP6vcgxVoBTLEzEp2pwdryq4m4cwKvfhnI8+BMU2d3syzsUHeoLu+FHXkLhkQdzT9oSBnGEKHkxRW0Oa2ghjVxLMseZhCX+O'
    b'v6XD5ayb3Jq5VLUUDqj5cIkCf6eEK7i+F4Tl0rpKky6yxzRhyU0BATyni+Qm4v+WIB6xA/Pt1N5kcF9JFvkmRvJkaVO37SYPqJCU'
    b'7NdVUnVFyWM7E6zv8zKhvL3XF3WZM2z5Zcu3BBai5PICeVJ1XhxEBRq0M27TLXpSIhGKkII7kKOvDXRZVFlxVWSrpARpgBoW4Bnu'
    b'FgYMvZOGEnLRGZ/MNweFuBmPlGl60hnnQe/Gq2bFHYMFic9W6WXeed4mBcJzR7MO89mhbWw0+tl6rsSCxtSFdjTEP3l6A1FxLCPY'
    b'6oMaa7EURuA9ZfaigQ10aPWCUUVfJ+8UmOxkPhJn27aMBNwmfvQ1MOwvodGg3oUdo1AdkBdfnmS3McmIPKJE6pcHyAioFaVQg/Za'
    b'Lox4AkOzJaGanEqgujFXIYM3+hDUlzTLBbG8Cdepoonn742lJGYyCN7rhA49CWozfnA+kXLQ1f3hqP8Eb5oY88sKs1gpBS2A1oif'
    b'JYTy3WMfjK7/pRGxqOSCecOOG8u5JsWAesLA00LbKZnshCIPiRCapuTsCzUS5yH+gkVqmN+Yuku+RFRZSM2R6eIofbCgnJLt6Hoz'
    b'9W/hlb8NqhiiLeIWD39cQwRbjMgQZWCAxBMlUSxhvkC7Q5rtOs1eDGn2wm52vT1h17sTdg3NNQms0M5M3I+7vo8vFnRAzlogp9iM'
    b'XW+zx6zZFru5NWZP2PUufNs1v72Aby/UNwkny8FzRR0UAVE6htDJIMWYBj1YznvyltOJmDY5utFEW+YqwXAAn4vpPRUDJDrjbMBO'
    b'G4mxdNhnA/bbyKNlNB6w60baLb0xF8rRflnrHDXbbJOdbY+tjYE/vtRRswtVdgNVYLWj5gVUeWFXMfr37nOkNhpEN/KHb9vMMenN'
    b'dgc04+PUm8kf9zokfDpwTrSVfapNk4cC5bJQqVEOKj7k2YO6oKrdlI2xSBzJa/aYjqhc5ineLdnTYzk4UQOrq20R2mGAqKDIoMV0'
    b'1kIU2dwmFz10mFhICJ1FPZ0VsO1S4w1K8WwuVfAQMlkqZ+IJK7IblHcpNUuTVOe5aDZWlBqn0TSPwAICjGc3rR2l+JYzBRzgrRPL'
    b'fVpAhOOiODWiNt+aGbLZN2x7y5Jmu95xF2A5cXs7FXR6tDX9WrsvsBrQEVyE21sIrN9dNGP/U2hHk+Yv6u0EoeiPmleSGMgvR5SI'
    b'/dZx28G+18778u0Mevp2nEds59mQhqT6Nh/NQc8f6e0NBDpkqEaqQrP5kAGbaQ1N3H8P/O0O/hoHH9J4SvsGXhmH2l9555mojAPr'
    b'r7z7YsH5bP3V38FHesfCRND5Y9he+/suPsq7LxxM5KcABPTwG86xuuxvbU05gkF0wfR+lEHwiYWJRHBP4JHdcRGxPo0IrsUmnLVg'
    b'PZxEBLcAXuQXbr01L64YjvHmyl/r1hkGqLdUv9atOwzZeLCHPr3TBz6+pr7EWIWt6fZX7LE0nrIP8Sam2kQ7rwlKLfTZbE13jLbW'
    b'Qd+E1zvcdndHb2teBmzb0++23jZwUtaNffuFAcN7ihDG7587MMZhmqbPAGMdaaNzmsbB/Lt+q+GX58goZvGTUkjsiU/dRiQTyVS0'
    b'0MTicP4vTDrdDqWPvlpHHjXbOzF0BRvtwGx2nlHhzjNP4e4LKtx94RaC7jMG3aeta4YzHhdAZm1Pn5vSu78jNhOFW04hHEYqhSuF'
    b'iY6wPg/8YLSHC0NfVHc7usDcovDk97aed7GXZtyxKvHZEc0omoXA6lSmXJu/S0BeChMbPzJS06tQUHvsOTo87b5YTNgu/nPn2QJj'
    b'v+/gr+2dBQmZu7ziIabt/UB88+2MPdMXm1YRPu9Yn/HR5HvDF99cerGrfN3h5y6Y5oonxEtTa48M5iPTR4vCU+OLsTaC/OYfiQqf'
    b'aAIq+m7iJiLSMegRZUahUMmu9Mnjz2PFgXTcuvcMR/D+IKHcIB7tN2G/ZHdyyW+cIB5iqCfzPvVwWU/YBdzMG/38bm2PJ+aXr79W'
    b'beAtuKFXiJqPrUzJ0g+uSiqeMPmar692qxZJoC4YgJ+1sgnGscn0+0iLdjKnhEZlLV3vyhpt2KU3MvxGpYfIAja6KGTli8KsDL/N'
    b'ygt0617kGeacx38nmNoZ/vMt26Lq29OtO/2I0ej42YEAZbfi9LjnZsD2hw+XbdSfYF42LcjF4LOy7pRgBkS56gYgfhDaDtx/IYUl'
    b'/OuiEN56MpP1DdvEIljTU0hiHW1Pn321AyQNfk4yvUnSNEIb+5v+totbCsm9k2UebW5P2LaZzrpaTi/aLknBj6/BHYZ1ERuLEUMi'
    b'9RaDMwCP+7Asiy6+TspLYTZPNwgl8YQHA7cfy7AamdhTukCMrWww5pY6xs2hLTzuYzPQifhGg4cvkNXG6ZBsQB1nBdmajH/NjmUE'
    b'DK0W6V2ssUgvXlzIE3CKRCwsA/Sb1sXZoBSogzOg0gThDJJi29NSxk2arqri1xUENhAuu1IFA7uurVVgFZ+wF274kMCySd0qXw8E'
    b'F6vh5l1kaDZ092OqdbLpH8Yevw0EkVLAnvjmjTnW9H7HZkr7ohOt/+0BzSGtGZVCvHBUT95EO8CkwLC3pttb7DGuq0TQ0AI61epv'
    b'Y0IvavDcacA3RkxUJFPTegW9V15FNBVRLvp4yF5ptQnoRK4zxwY6Hkiq9KJueDLdIruhmw0AKHEC+A/kVXqrX3y89kXV0eigCl8L'
    b'WIVQyzEgM31wULnIAHXif36HgCTG4unfY5HTCSIrY5DHyKI9wDeMBnJe1mdJyeKD/XffHUGO2oOjn98cvT58/e5tfLB/8NOh2JFw'
    b'DcenH8OehOuTuYGks1SyEmfjekZFYs96sawr8JToj/Gi+tqjvrToGIheRntspEevdhPCuWE1RJ3jpLrsLae8eLWnypu6Lj0BOUyf'
    b'6zpbITdNyZfK4mxK/wI371WZRyOxydrzrBbmxDcXWB7hOUBQJt452zIHH1g+/V6QvM4gcHK1+iHKan1AcX29cLDEbiqsrWbsxOAe'
    b'L3Ny6hF/gLAhKCbmDPIumztz78hpGI7TgjYFyCEiXn5Z7XSt6Zm+CHTAYRXkSRGJvIpKaPCVqdnIsBsTxmISuhklwe5LXTToD7Po'
    b'Dcoi4h/vfPQBWa/8Jh1P4xjs7+JYpg3hWUPCaGmmgUWzfEBL6lMQDVmurdIlTTQUmbwu6rrNJYqNZRoPQrZt1+ytyU47XXVF2YrN'
    b'AFnb+XIVZ/lVkYJJxarqgIOnzCDFeVVr4T/5oEY/vnk/QiddysPrAIjGY8WXjA7evB8Ni8xAVXk02rylSKNZXEH8avQVjIEGR5Ih'
    b'MikIw3RI0jns75rBmGGk4lKBJrz19jMGuJ5YEMKCxaC/zMaGAz1mC+9IuTOtMfF3O/3u++Q22h77POjxyS5vY4zBgf6VHv4uB36F'
    b'R/2VibdxzdiM0BEsnfAnk+Pkr7XP5tuTrdtnYKcHEQWLvkCoRM4sSoJVCR8FpS3JaUWt+SelcMZVUqr07ebwvU17GE+dP1dwLQt+'
    b'u0O13VoTYwf11nUFqrxk3mF8R06U8wWBzOkShJWHqSlqt8E3wfoigQo0szdD/JVJC37/BNiYCDVDyenm9ml4MvD3iH3X1Jd5w/Kr'
    b'IsvBargA11Zc+DyDaMtwr8kHGBJQlO2U7dM8Nn3W2I+UGRqEIRVOqBhLRPRwXVRZfQ0dkeGa9BP2QAPvVYlj7LGwMqkykIND7HIy'
    b'v0XQf2BmyFwFbtnkFwVkubgVx7jJF5BQTnjNbsJgTO8V+JMYDZK0rcF5amO8Lh4KlE0bqxLjKPmdPMyTqMyglatpdKJGAnEQtBan'
    b'E/5oEJ8yg9fYMngVl1xrpWPKkzWc6unGxsb3hwcv3748em2aU749en98cKgFzyVxiXptMYyFDGqfL87ypr0olrG/gkzY4S/25tdY'
    b'k3TDW8zjJ4kyzNiQlOUIwgIIT33+XLSU6pofjFWXkkMHpeekvfHZz2L8W2TSWA6++aY9Z1fjXYAUCkCnZuz1X94eMroLRcXevzvg'
    b'Lvmv62qTj4B78vMjLqg49DGn4D7pBWiNGMjqQDgIJ1LJuBEaOMZnOcjWgPXcnDd5zuZJWZ4lKUbVyvKyOIN8GGCNDjbtFDviCtLf'
    b'7O49/3rv+dcwNu6b3cIkIFMEORFcSlP7LLnlcwFBXqKZ8So39oCzOk7ReTuE4N56LCZs1aXacW/ylvJpqltDltPCboiLEA2P75Ho'
    b'5cWzE/AzeP/u4JQ/Q4TQZjQq52HF0sDjSiMRNReQVDkQ51QA71yKBG5klpddEl3Uq6ad7exOQPwBsRJmz7+eMB78cvacC+jFaYKn'
    b'KU1KIHtjcRiiEZyw0XgqKin1jnqNYX2KbLooqkiECFU8rHB2EpWSG6sSN5XGa3JGOXgM5tzAMdx8y41DumfZAwO48bT7DfIoXOVN'
    b'F43evzvQyATAVHw/5fURcwTZMuVggBKQeHX5ouU7SBz4ZX4L501uQts1czxyo9/9ZfN3i83fCRNwFZVJP5jQfLpI+DjFtMe9J5Vr'
    b'BzBkh4pRBeBi5e4TzTHAx8BI2z8nEC4CDw96uZETDLdah8dICxmxAkUNBbXQLd85vgEMIfOOiBVtWeI0hbQxoFHH6wybdVYW7QV5'
    b'wAphYLFYLUzzegznyn4oSkBdAEO9CFiGm96yRQIv+hVSAbT69TXOofkDfLrFROeUJhhUEEtQ07Q1S0TUDxpjlsMbwBFmyyBByxnP'
    b'Zt0ZiYjfvHynCfFNjMQTCcNy68JRtcoOspJHE/IB+xxuJkH8BC3oZugXzzpKskAcKf36iYdNM87oeck+zVC17rnf42oBAkw2hGQw'
    b'80JQ03X5lB3rBK4tdLaC5z9dLarTtY9HYPUULWYM4cSuKtwGRzx5EESbkxorXpJUGZyxfGSHEiV/NvXN9XKDmYwUB7VskPHHC66U'
    b'LLK8F5MhKGHTYtFZAMWZmQ5MiTQF1He/+2nvdz/v/e7tf6ML48mMKnlmyvwWF1mLXmIODWWrNTl29jiYucTAODRpoUQccZLJQeiU'
    b'eRMeXugPMEnT0cE42TrVLS74VKosPY+TLr6MbuOuWeVmdDaex8n8eImaATZju2Cn9S0peKXmDzQcBIpyfAitBwdlJ/5Q2s4qIS6L'
    b'GpPFUZVUMel3OUzTgmLCqqSaSatD4E2X06KdF1XR5WIU06S61WOFSvj8H5um7r6Qw+cnDPI68HBuzTksZ7Qp5nKyd8lTSmd5UjqV'
    b'EIqsc46IG+ssMffCDpi2Ua0T7AXU4aCGVyDj3kZYxWiUFS0K0KAJxVyrltOyPt9BYwQyxNqZ4H5gj0CcibC7WQoyZLkWYE1FvT9W'
    b'YIXwxFNXH6/bQtCH6Tl7Ss1B/Af/lXI+fgToWAo+H2PXQvxLnlcsorRtrv0BzxIsowaKnFfcHFAvuiWL4pF7km2jBS3aP/SqK7Pp'
    b'i1JlyxEIhM8raP5/aij+Os6l+DAijnW0x7Z4rsG4SONFnlSjPWXeIa+wU7JsxHPpFt8pzbccxufSe/ORTwjbXCUlJLqXY4PfaPAx'
    b'4f+Tr288Yefk+itsBh1/X7VocCLPBWPTrs7avJudyG3RT4JmoMER1jlqY1HFi2xJdDlh21u6bs/7VPN5CRMPHtxKdQoq6KaJzk+0'
    b'vjHk5UWdzUYtsJOLpBrpNkESO5mWLRYI57lwbUs0iDgeD0g1zvtBlLtoTtx+SuTzMWGXs0t9kv04VWwAbcxYy0ZfL7W3wUW0wYbm'
    b'WTNHDZXBvgHHpGwt2Bdo9SC6VAVg8wMnReFQNN0x0JyRqIPfYNB1QBt+ZnSi2L7Zpi1ZorWB88p/GDZeCpSDDBxgcvcInPwZAOjH'
    b'IQ5Uc4kJtHXFHfiQpekRO8aMmJtaNEKZSF7EGURBYcsiCirO9nE1V1h78yyBaIbchaUdQ3rhYwzYW7RsAee+qc9A3AvotgMdJs9w'
    b'3v6BCeUmy+pFUaG0BuWteZUBS3fe1NfdBSO2G/MWv8OASMCvYQjFpBUjQ/sBHm4SEgaxo6O3lMwUPlCYCJJuiWTHmjDr+PDHlz8f'
    b'xoev3x7+DDmWKLhg/Ob45dHx27UmlcTgcaQItn3q78OoLKo8ARX+1nQHnhCpdIcvz57zRwXtALamu8951o4RzTxucszpyWEa0Laf'
    b'29Ce71jQdgU0SCQ7L5GWV8MzoO06Y9v9yoK2I6BdJ01cF5DrFyIzXNQpJOs2oTljwy86tC0BLU2a5jZeVSCdl4Mzoe2sHZuE1t62'
    b'XQ65dNOmaAu49Ta0Z+5MrXXb+epO5S+TYrQsFneCuzS0FFI5nZ9HfpdxPy3TJGD1quEnOTbAacqZQvZG5cKPguIOmwnTxVQCACAB'
    b'Qai1nHagLaI6T2NucAI5nYF8WS2iJhFmtoC760ZSxAIjXwqcdcWeUktSDFxO2BXcegDAJWpi8UF3vgISlFL2agjK2QxiJbn+ZqCr'
    b'I3xO2rgmntdKOcXVqtzucq359Wg0OqDRsmXebNKIbTTKE9UdHb0VI5UY9bsxF5n9UDck4r+s6msM2waAMFoD9bQJAq8ub1qEw3Ux'
    b'MqotBoehRrw2HxZYTpAhQgHRZjdllN2XBxBMBuVpy7zhoXyl1QIH8h2g1pYway+2VE/EmNCtNkhA25QCWUwkKcuWobqgq4VJWT94'
    b'A4UXVbuaz4u0gIEizGM8bC3tEj82PEaqhgWuTRQAP+VFuL47NUV2XN+KViBG2FSRSdrBCyKR1wQtWTz2aR846Q8vp2gFJNVAXKPM'
    b'I6UmThgEDhugajqasBdjZS0I73N13l3orCVaZQ+DK5pjdPTnW4QxJui6wdnWNF5ARMRe6EmWLFHXZmKhIuX9IPTfe6BfJOU8Los5'
    b'qiwkPlsLPE8hFbZsrFYGPFSwlx3uM9Tli+W9YEMDUIBRBGMJj6/2vKzrRvOhG7ocvJ1ajG25GFvTr5+LGGPFXGIZjW3mnxTfbDN0'
    b'gjUWFYO8sca/qrqfi4FFxZnNWzqNpRRKofVAep9ACB7VbqAtiROERw7WZ2PNvuE9n1r2NLgRQizSEzrSWnuILtblzaKocuOlEKLv'
    b'CBSoQCUDjkU5rEqNWq+65UrmlOAPLLzm0vAJxe+UFZpFI8wDgvHFY3Df6AivYt55/KhjW/hq/NZ9DOcSaCBWpTEaqGuUokumWD6t'
    b'akgjKtZKPmlQG3Cm9iCQsIqTWiPzdeBlaQJ3Tb0T/DP/zdV/8GTzhYAekGHtfc+mICMWjgWk5h3gwiV3h+95UZldqzUQNkC9g+AP'
    b'pZ7++rV4igiCCS/W6T4yKPJSfqoBvGwwdIMG1GCZlCC3UZK0oHUu8PWnC6a2/1T3mgUJtz0n2/NDA3ZPHxBbdCUdQbQn2Q70+7ru'
    b'WF7Vq/MLsWcCNUNSb4grSDslMybU4DAgSCKgE8w7gDkAwOH02RaALxWTrlFIyVkrKDijIbrWmcnt8PTucbiPtV2jlC4Tg1Q5uTwF'
    b'sTUmE9mkNmP22K7iwMctxhjGWkWjFt0i8aefMj7u8DlT90ecZue8eU6aACvPmlfYqN0LQeObtHSWp8mtS0pLjMNTZhVC8iEB8trx'
    b'IlnuOZdduWuK1QPF30REgjXxmZiCE+9fE3ZrRz4cJFgb0gn0B8PQdEPeBdI/CmtWRI/C01BOSEtfoFe+7tbVhOkn5/mEmsBschSj'
    b'kiExWnll4iZ64jKDaFq/8b2330mBhXBNdyYbuCP31pQcpsDbJ/je9kTHD64w/AkR5Iydn+hibtmrV8rtgAnKunU49xFMrxd531/Y'
    b'Lf5AEgwGEiBjFpoCD88DK4MGklD/cjQB1RKQ3Vwm7YDtF4Vjpy4u61U3BtpIYaxKLdUr+cY+XLE3QlfOquZxEShBoKFQ0H3OiD02'
    b'xMhC0auURVy36/YEf/IFIGDjADQlmKawJFAPdahh6O4XE6uoSOnWfMMNrztL67A1fc4eP2ZRcp6zp4p1tMMbg72d0TdKmuFJ0iCj'
    b'r8QwVKoyu4KN6HkemdBFMpZ2poM3h+S60oQ6EwpdUWfVcjMUeBivjJdQay6eEoPPudIeR465CBqgrx2b3AHBjpTrmBSk96HW6A0P'
    b'jvU9xG/rebdIbhiY2spHl9bQeV25elPZHtHIPZnW4K+9KOYgF5uZ7YWRgv6RzBY1Z3POqtPSQ4o1lBg8FjC9NcU/RRyE67yZcQ6/'
    b'tz6EnhJNMfCKvjwor9tD4ZtQgvyPf//vSr7zP/79/9aJS0yPxckhEvKZm8ZhDKVRbCLPPB6JJvKQMwAyk8gbg4zEk2ydfz4Yeco5'
    b'FhJzc0hRqvdETf4xDMGem8HU8G9hclMsqk1jGsBMWlPAdPmaR+yHokpKQX4bmiu5F4w4LUY+xFyXBfvL+QlNxjrPtZNDV4ur8TT8'
    b'gwkAt6YQRFMoUwUjs6kxMhjYQLOPhYE63MPlntmNj4EQu2bwDnor2DdVaWM453Bnjs7YSPwS3sY1HIMGz9xLAmvupGmrbSowXBle'
    b'2wHl+h+ltFB+2x8lcsZBm9orEYF/z4AsQkSoehxtgqbwUhjA+Pf1TmvFlybWrHBUYYIeGaZrtkwdHwVk9u5OKGk99+PEU7JOcuqI'
    b'mXBteiWiEFM/IGsNS/oILEL9p0D18wlUtd2zBUWKbBgULMQTLQQdWiyxkLO9ZV1fIsUUUua4J1c0URqL7R1NmTNAQeTCDKqGFCQe'
    b'bUT0vieXfr0wDKd7Yl9rQFvCOEew8D0b9NnVPJ9XS+XKoRVKCwmkVY2AYFpVCAiodfQ4UOp0b4nToMRXA+VLjuRjsFxJMk6c9gzX'
    b'/AiZ0nlQw3MP2dH95UaGzOj5wBydn0BW9FnkRJ9aRqTLVzwnSq0dBAz0sOu6fAnQkZAx/VO+NFy29LFypc8jU/K4L99XlmRhlXvL'
    b'kgbIkQiyR5b0aeRIHHxfSJZ1MqRPID/iFIBgB6AHrenGA4iEPmmUSzzcXyb0iY0+HiheGiZaGiQm+rymJ/eVbg0e8kDbJB+rrVkl'
    b'vXjuUmRSqGHSPWEpluzj4YIs7LNPhEVgPTAsSZYcCh3WYbIPOeN1ClJL0KFdT8H4IzKCWnohZ82NYE7mXdRimvYKR/wxMrGCJvsw'
    b'JR3cHZLr+CQd6Knt2FdYEhSve/Q+jNo17QQn4Dk34vwzCOf+ag7gryBLAJfsIgMHY9EMBHawDkWekeVofY0nB+OrSIdl3banqNhf'
    b'/cY4f2URxF8AO1DLqPKv9q79dSxiOEBMFxSBCO204QhA5qBI4wFYad355DuW3VbJAtwg+EqMreALQCIbsTxpLJr0KYpIolQ37MPd'
    b'mFyGZUpH/hWdv7CWEzyU31c6bJCJGsQ9HpD8NKpAXWGQWEOXyikOGh4fD3DrmQJ5KZRv9fVCl1CjozxwxQs5bB3ES2ideU3ErAzF'
    b'xCnTD5X2YvoswT7SGsxjldBvAbbeCsy0BPNag/mzTeKIMEhDyHpIevhKlw6TFMxORpasVPDp5O8M8DGKgzPgMlmcZQlrBNI1dwv3'
    b'vZlY14QfB2maZpZahUj69tG+nrFLicJnHL3swz9+rfghM+Aijs84fiFE8Y5eFg4Zu2067Xsp/cR5/7HjpOnaw3Gv0xAGau/YPbYo'
    b'DNRcyHusnMLa5rJ94iX7DMv1iZdqyDIJZYJLdmlV8Sml3+NwgwCLZn522wsex9kLk8nn1Ywt0QIOhOF6NqUHsgqDOwS2szs9kHld'
    b'B66VczfJIGJ2lpfEu4sc1TwFsTf9LuYSN4IXQyx/nrtU0rm64lAQtgGyFog10Z8R9BsefbLJ5Z1KhsKU+66R+mYnKYxgS0RJOBn9'
    b'BtsfNzntErmIxr9F2Yns6WQka5y6Ca4kiOUaAMtwc/CM6x+BrNEHom8EvNzTHKVhRN2oxZXnRoUrlfWAZJI//EuNQ8Lm1ohEO884'
    b'HJSpQdD2y1BIUNmL5xBnwtxKTG9lfF+OTk0YoLCwAaidMAHw5TMBaHdQGy7WuarLeInZzuTkr4uqpXgs2ckIynee76C8GrOTeLY1'
    b'64WQZfH2bU/zsvg13H4TANRlmTQxjmSrbyCLerEdX+QJmG1govlYJpqP1dZCRpF6AWlmx7qMBYXkztSKtosXyc7W1iC4qvoA2Oik'
    b'elGcXwwCjbWf71xTi2XaDeihaYvtNdkXwf4TatlpF8/i5dnalljLzjPZFjwukpHpDKzOYJoxlHcXkESkLjPk0dL5ucuhvfiKX6Sz'
    b's15wOIQhACEzlBwgX/AoohXa1EYNRqPbuJrrVvfsTMGh9dpUowUwqB9dCwZ99wWkpr7GcAWKFjcDpK891btrTvXkfuBeDAanRdTK'
    b'eIBH/OB9BeT2tcU59EuRb1CuJ6HwhIHyTpu5BCGnn3U5zQqQ68K8YUb5NiBMcRTcEr63boHarcDs5NS6psBcYN5ju8yrpOxuRaW+'
    b'Y/v8uQkXcwH1Q8UqfTB3CSaIAzIMmoByjXXXnQdzNFvxveP+q9ZZmbDVcpk3M5kmrsyTjAegrZKmqa8pC8Cgfn1th/bLQSgsBKEd'
    b'hnZstuIsxLoeZaMF5IUDaWVjHG/dqA5O13M4XUJAj7laNq39CSfH1Jt6VxhVfm5mSnlZdAD+pQIIO18FclvqN5qfQesym6dXfn7s'
    b'WyatNLJyZQUxR7/um20619LBavw6+3cV0uORGN25fE3RXg69eDLk2clIb4ZrRZAfs2hr+nv2WJJlsD3wm9NY8BOwIqeZQLXhXXwf'
    b'10SJb7TsOhSFAzgi9nfTZlLLe+YEQP0ZGK/vVlVWciIYpjpjXW1aPi4TEgJDACj8t+aHj6yb6AL5KO2D5OYUqIukzZ/Fc1AqNvkK'
    b'w4NX53mzbIB3JiUWr4OQVIzBsj6PRm+giD3bE+pkTDC0yddAhipn0+mUt5KJJrSsFrO+lD9mKz16JWXCcOEFU2IgKDfTCQp0A1A8'
    b'eVFMMJQaZQgInkTFai7yqAyCIJOuEBDIu9LXTsvLwu3+3HVUvBbsp0HAjE7+vH/8+pTJPZaJV1aVbP8HYeWD8brBPpyYMoxOb54G'
    b'PD/tlJFCRvzNR02etHU1+xCax5eIfr5E1cOXxNi3XVKWefblnYKlZW4Tp/++5q7I046+x7IAR4t+/zzmqUjA9YGa7Dkd3H2e2AN2'
    b'0l4vMLNKOP2IU9VKn4shO2FdfOamZlXDUsQ3Sg8IuWcpGNuL0PVwdsQjJDAWtymgHQBj2JiLfhygEzbqihR5ckjZ3eYdz3EGtm0i'
    b'TrWRS9JEmoYoab5WlDQXognCv5ddmizjtL6SL1l2MqKv2oohH0K6P0oaJ6hHHuxzrgPCXL47moGdjOhgwz31yFDgXs/FXUaMzGGz'
    b'FDMDnEPE/pqV9TWLPqhe96Y7v7sb/4G1l8VyCZebijaxJ0gA0eWNQOpyPMub0akkDtC0DZ5xsL3FoL58u2FpHOLDFUT4UyZCTkYA'
    b'IACb7XgHMThjWUlYk5sou5LpWuXKX0mjaSNNqtgGaTJEQMd0F6iDb2ZsO97e2oq3tuiO+MfEvuUNBuBaqyWlGGhFIPCnZX29icSM'
    b'i0X3V1292eRlcoOb5Y4Cgz198A9xbzLdmt+Bhv751tZka2trqiNW8S+59s9pzoLiot2/MjeeKp+a58OPaqxKDYiPZCH7O+INYL6d'
    b'by8WPiCYW7pNqqIDIZe6NIqJNu+7Rq7zzkFwAx3if1/w/27v8H/sPBM1qOgsr9KLWDQUv3aNX1bNHeMnByhbUmVxt9Ww4RTMtvPt'
    b'Z3pQdFy2vAGtAKobYz0mPXBaktSTC9xeAPqk2iJ1mrq3ZmpqTBgt7YURzm2clCUlmoZ/oTXaZR5TQNLW7FIzycUIy0lZagVFRZ85'
    b'JELKGOU+5p2IX7yG/ICT1Hvn36+Lqsqb0FjMSsQb6P3564lhWmPxVzZzx6nTZ49bFnyhwbjHlnDsKekbvjcyexc+gJQ9DW1bNAHS'
    b'sLBF8BcOs3sin1hVuRJOJ+qTm9+cY3HMiB2bo20lxvbOYsrTaCvc7a1mvaSL5Oa+3aCZ4336UPl4AOkRK9gmsInCUkdgXaNM0mBq'
    b'czwuYnAakrSLZfYgHUaMCN8J8SbhwaO0Bd4v/vX+Rip1+7vERSQQvOlownaeCw2ipnwTTdGoMujo43Zgr81owr7aQlPV7S0uHsDD'
    b'S0ZeUJ8DNzqkCAwgbMmLMgpM+jHb3jFNIyyo3ODev2cTvbZhUK1D+abvTFgWQDYpAH+Kr+bz2xRLxSk4KZRneALyzKIHEOWM6Mnv'
    b'GQo++R+0kd954QSWcvbB/30PiImJF5LnOs4+eD4iiLFGhSjcIf76b502pw0j+5Ivv6HtVeFN5wdv8sh0o6M8D3JUTVK0OTteVcCE'
    b'HQL1ahF5r2uGqWqEd7QUZgAn4pWceLjl+rqlJGeQyA0ib84+EAtxB7mbBZpGqmj2AQ5ydvKlib6/tDg3aGl3Iyg1E45Ovw2BQgZQ'
    b'OhAcTby9+NIk5r4Egsn99kL7JruxSVNnt8gwdQZWCNHgjQXpAlx59V2JuTbce2nslgLLj5ka4nz0AT9Btg1KCHUHgj7+cXNbfdXb'
    b'RGKhcTSzD+bA7twEnLMP/lW44+5k4pBAr+O7schmgv+RKV+Bq+pJB4uGko4czsrJ6q1kM6My0DaAx9SwYP0t+7pTWUzwVoPz2632'
    b'mMBq6InM1+cdz5MGJApdjaxs3NQriB9rQgTlvrcemOjzpVomDQTZIsk4T2OqMrIrj0og3yijGLru5kKOScJrEEqsICMWh6bNRY+V'
    b'V6O0D8wI6yTTK8WiLELhrx5dgb6TOBeOv/hCAsH8pmuS0USZ9WqyXh296VOFLtjMSBxvrgLWsEcCnLMGYIoJ8cALBygSY5gzJYI2'
    b'H0Yj47A9Kn0DQJEDY/p1lXeR3ut4TfMhcrl1LXoCc4o/+0D8nU6EU2/IAJWHdyghkG46LHy/na6slzSYR7lv2e1zL7Z90OYG1gSO'
    b'rJ6h0zy+VqMR5AYRERDB/w2urLhz4ayfVINEO3oN73IK6Z/V9anRJwVBASFjkeaar76csRmfRL9Kqml+ExUTE+WZu4TJACc0B+UZ'
    b'TBjdqPhxU5OgyJ1B+CR1bbzMG4FqgaPcYU8kbyOy8nBGZNz7WGy57+pcPKxsWSbVnlxZ/e0ydnh891R/0HTKAxQK2iJKGMbXu4ns'
    b'g3+3ejH31O5BTs1emG9mH+xPd5yK5Qe1rtsYaDg8o8a1OpXJlI3PPIIELh13FwdDtrTO55DjVTmRq42sanAFo3XmKdvkhLIbzSaz'
    b'qNALXXpWiMooY2zu56RkAGhy3fQTE3B466XlXKv3qj4v2q5IuaKrqCtvIy4tGdoHr/6grtKzxh/UxqqVDqrVXA6oRiED6SJJLad7'
    b'x0jg7FyxsQGLBJ0ySSKZT2ljMJKz64MBqT86vlkhIeQZs6Lf4BlFnsoqcDl7uxzz1tFIVRnP6KCLOtriNxlpgZ/bk1OlyCmymwly'
    b'V3HW+VCkpj2BTCGXOVCUBp7kjf3Y0uD0BQAXe65JEIVdLIDo9WrD4MHko9D7k600nZzZkdquE30rTtmTGdseMKQMLACzE9mREyBC'
    b'YQ+LFjQfMNiDwBNW5bmk1IHRMDCNHtjIRVjsX2baAPSV0YFaYd2oftbZu0yMlwJnxbTw3hjwBhbwfL3wcwpsl14VQoohnZQfzedA'
    b'3tyCMmcGl5layJA5WDAOg+ZHxqUZXVUv6F7cYbkk4Be+tt+owftakHwa6O3bmJJdoykX6hNGk1Dbnnnxc+fM1VQ4aBsOT7QFYXwf'
    b'aVvfFnuRgUvN8+Np7rlAPB+z4y704LaHt94zPLeXnv0PznvQCQi2dr/4zoE7e2+kGvdZEAEwREgG+4i4YVQ/xUHSsa77znmQrz98'
    b'KPzNC0DCmFW3yGg52mVZdAbbT/Cxij121HOhCEPlejY8nmT3Jt4Fb3nxIxKDMNWjZvtfgOQFJIfO8lZDE3g/oFsOiNpqekJvcB7Q'
    b'uTn1QS/nq/0LLQIPTgHPYRRBSAjrFNzq1TCXbXRivQa0HagFa816IjQHps7Vm4AJHcjiMJxhJzeUU/FAtPmFUd9yel07owKUe/LU'
    b'DI19EJ3dbyfMtRAw1uyIZ3XsLMgKkqth9J7JJgdjRyTko6RcXiSIOBv4HePvCe5+UXUgaVlSHuMJeCFl9YLCNFAL/iHXY9xaHU3n'
    b'RRfhYYa0lPPC2kWdw5IxebTWWOZ/nqqliL4nTu0YDSKssMT6eNISLrzLkkQHOJ8ShCDncTpBbWbRgSn0ztbWfWZu9WbMXoxyQFhn'
    b'c8DILZhojFgtuqPqsjpwxCUO6s57NN/D6BKBkngXo4n/2TeheV8bl+u0YxF4amkL5DkixjKRtUxyE4HpTa9W6+lT9syTTQD3kXfs'
    b'YGa9p4egBQXAMdoyYHuMKx4WV9+73IQTvDQJIQozYaCGMiB4zdb0989FdCAvDA9W8dbru29ui/GAuamLyD8iNpIL69kRvK3hTfHP'
    b'r2+n8Bl19sqdjTLv0tPGh7YxgAzVzAgn4oMIVJtVzHV94mpAmkyotTXdAuckzB9vw/PcDM+aB1GttzH8HViHS2BjOlnotrHzPHCw'
    b'4M/E2cFq9ztbuCMD5+s7Y9bi+d/j9KzpQ3XpWdpf3Fz2lX8KOZcNM8Taeb87r3ef4rJXK+UummOyHz5fJbgJzlcV+gnORsc/vz3U'
    b'Iqjaf3CSkLonrpI8lc9j9TncNMuX3YVshb/ClTH2OZKn4jxCI+Pr+rOc59mwowx/V3lzVrf5TIuf7fuTWuKZ/Nd9rgfcgstryJJi'
    b'JgsYTHr7AQWrwR+aHcRtDrLRiJPugOfxHz2YA9vCSM5QLsclpOHnSfXn4zBGe37OIwzrbt1Bd4joCXv8WC2MuwPrNY1WD14qcx2h'
    b'HUAZD7rMgOJcJ6DBt/lVfQ5f7neh07L954X+r3ehDc5Zk038F77hqY9R/NSXXFIR699j6WVhEQkPe6eBPDG98wbf67/kXQFN3iRF'
    b'c120ec8Fx7OyyLumSGfz0evvD36ElFxo9Shtj6w0YeMJez6+uycVgOGM/0kGDMMaxFgvyYES/CStZ0xIsWa2UEvwUI5I6zNjJzwc'
    b'5nhNOkIbsy6X8w/rI/CdHMh/XazWXCJaU2fgk5MtvYyPoUvV9JobOupbqx4FwYiTZNjVSuja9T51sPz6C6qObTkS1xIPlyDxGEya'
    b'phekHRBaqkjhRQGAhlJdFy2Gw2XChmkwgbvlMMEo8iwRkE/2Jmxb+aa40kwBqVpOf8ubukW1EZ+lGSjdI5AKjk/W0SeuSXtC83fH'
    b'Z0C69yB7F5HX0ddRExY8bDk1mIHByuo8uJa+i2eNvTLGiThr3HAPa5YEI3UZXaR9MzO7S+/dHT6+AN+c1aVvWpFXAIKEjY5AtCEo'
    b'x9Tehe0wMjwvsCXZ3WJ5MsLIbnqgO/7vQC2KJIf/8tQwpYgCojq3a5sQeHFyPNX1gHj834FaBAr/5amhQtCJbbLWLBTz0Dji3WJp'
    b'PjnumylDBO4xc63dt4oHA9QrLn3VxBqIiuJ3oKqCSL881XA1RC38YVbSMp7BXzo/BxpTfdSMgkQ4SpGeDIXRaV2lSRcJO8cJK84r'
    b'WFQ0ESL3e7gG0g4Sz3bAnlj2IHK9rUthZw8J9eITLUXdzDFRIArPDL/rGF2IfmWQZhmT3MlU95AxwF8x97n/2QFURTo82+UPEQgg'
    b'DLt3UjwbPeGKG+SJgSfk2x9aZLgJ1taA2Ze+gJxuNj86vWQ8NaV17RA+Tr+o0nKV5XGbdHlZFl3Owzf4Rjuv01XLIUFggzK5lZBU'
    b'C3HshFK3Wyy1V8M05psmWRYJYz9fLbCzNUgqnfZSppIW3bXWCQT30j1/mm3vjLkW0UZ9yNBptvmdNNbWTUrSizy9XNZF1XF7PTQu'
    b'VLAspQof7Ke/6Bpw0GYJb45hXidwTqBLUhabxHACySh8rjMOYkRYLr60zoRbwc86ac4K6DM82sMts6AFREMjuhXk5UANe6uXCY+a'
    b'o0CP9qSZaqCR7vuzp/w03NrWg2AZSqBDl7Te56tLfqs0Gt2G356+acXPIor/Mvsghn43HnECh5vGi8NkxGjxmAmbL7dRvlosEnyr'
    b'PO/3oqhGe8KJGIKGFFXkQh979mFErrBma3JYHwoguTFbQ3b1tU3veojy0Lz5NLcm2qjxB45g6+5eDq2Y9Beu93Xe5Ow8r9DoGtMp'
    b'fAqPVjJJdl0YXV/TAT4jbiPHyIJ8LV1Habdpj6XGrNfn2jOKe7pXb7vu1fdxrfY2V0/X7IP6N+yA5xTNPvi+Op65urvYgNfCbMO9'
    b'X9aFepJBCpM2pd2enZBdGD4Hp36o4EYXZ6tlWaToAt4XRGrCLvN8OUMsyx0BOBTtpcLXQ9nTAukFBrVP+QCzGCZO6G3K24w879Y9'
    b'HEQHPm2eZ633SfNgxYc+Zfd4xkZw2lZQS6ObPNUGPVrag8Udibm2gKTwQN1zb2mK3g1FPFR+RLs1YZIinfETNmEUVIa+qbSYlzOf'
    b'AB+7NUlkvvsDmBgxBkm4KiZAY1Duw5IYEBEkGDDKfHoYjaxaTq/aLkkvI934cTxhyU3RziiDkOF45golLGGg8IfO55BND16euch2'
    b'kpJDJggU4aX4DWKjGo0h32g+V9mL6VHK8qpe8IRiyVkbXREYTA4m+vHnGNNHgekCn3Jgen4xCcLMpX6GATnZTA/PqS5Zr0GCvRMz'
    b'83qpFLtwiFQqZfzK25hnW0+5a7QBft/bQKbgNarjgbXraxeHD0HgMzF8sUKqosG6zUxTz1DeYK3MzBesFRiZgu1GeCF9JZJR9Beb'
    b'AiiSitvLpQePtcpE2g0KVM3xgllF5JuCbCUQiiE4VO2jFuJLPI8zuE50azVsaWk9ZyGbKa0JR1rtMk/ts4cRy+SFBBcVqouYLd5e'
    b'WGiaQqIF6+966r/oqf/Cqc+LQdnSCkTna29UsIEI+SPGWNMb8wJzjjuLYHsIyrau/c6zcHuI4rau/a67CGa18Fr01LNBYlw5iDwt'
    b'M+S09QpsPPdYqIiCh2CUYAuYG2MuXtZlkd6O9tir/e8OX8X7f9p/+Wr/u5evXr77S/zm6NXLg794YZARXtysSoydagCG9D8d+4ZJ'
    b'iz2iyXyIynrbZ9ZvVdF9bSVOVnknzXyT3gfcTAxIwTTEe9HXW1Yk51UNVqfOK2BlLiIusKdzT5Y/e5949qQ9njspDMtOR+hHeaM9'
    b'D2EI0Roux3ve1ENXfXmV9TVG9UjP+MQAcKHlSofoPf1g+CWn1tpTrT0WPAPXZr5RfQoidPw1JiH0EGk8g6I9Zj5I+iA4B4qOTCwD'
    b'kUJEdojF+FtbV6Px9LopOkjqe9NF8GWarRbLNkpaXEZqweVhVTfb4WuPrAInlnmIXXhbMM5B0xXzJO00rsHiGCy6TIlBTU2w873J'
    b'NaWBprB1PyoFabDM2y4983SbnqXempeeEWoKOLfUazOs7xwPAU+LvrGx8a9Z0iUp2Ahu4P+z75L0Ehb7OG9XZUecG8RsK6pzK/g7'
    b'Fgk+neB6axBO0zNtQRQBLMt/XWG2sVVzlVtNNzYesbcdBPp9drZZFCza2dp5sbn1bHNna7zHtrfYsm66eV0WNbvIyyUEyYsEdyHi'
    b'qEEek7qJ02TZsul04xEXusN0+AMghO4YyL7Z3tra4iGc2+nydrqxoQ3jBXu7OusanirVGs7vWVzm50l6G6+qVZtn8WOW5UnGhPEV'
    b'JIZd1Fd5tvGIRZs7k92t378aT9l/y5uapRAWvGnBlhjsNDN2VSTsvMmXU/aqaLu9jUeM2eDFTOUixG2Z51eSpuXHIvr6xavxvdrT'
    b'sohjFW2/2PUDOFsVZSZecrUV9l/0/OsdP4CqbhZJWfwGhG13EZfFoujEsA0Iz7b9ALipB22xzCW4dGBEXwXWAPXqEG1Qor7AX7TT'
    b'N4I0aS/is9V8DiFcax+saOe5HwBcGTiAoY4VhMAuQNjrIUCi7dAipmleovCT5pHly7K+XeRVZ+/jlh8Aqcy0oGarpopryExhj+Br'
    b'P4Bl3szhKIAQS4g6/JsQWINmVeE0lh3CQOWQB0S0/exZ4ChzjNdzjBHAi62tvrvA36gmT+vFIq/InVkfSLT7PHCQIOM0Otj7YdAh'
    b'5dLA6MVXgVF0Yv2AGes5C7s0incXucj7DEE6cbD1nOVJeoEZtfOiuwArrsrBiyzSEDOAQrJiATEyIE47/DdpOdZ8zpm5lkXuOk9Y'
    b'3qXTMeFZyEiCgUMbAy0BhhAt+XsfzFJCdAON05vznKKxyEgyL8Hy9KzMMTTL2rzl6fw8rs/+5kltAqmVwX+d4mhBJ5hqmv5hW+Vw'
    b'MFNrjjT1ogX+GxoS4DJP+G8VoQtDUurBwbTuC0gNgKXfztg2z+Vw1okXEVyWnF2I+IgmYuk4pcDjPVkHK1LQUDRHLdVkgAKZjXiN'
    b'Hmtgnc/v6vQyhvQULbimR2gqyZ3XVG9TPgiRKeVcbydTB495THVYHFg3XB+1ilrcU02fbk/RGPSABZNi1grpiabI8hl0ZydXC63W'
    b'vLhBq4jAeiAoM/GpoZGGqYwtnYMLCrQDZsd9qSaM66jUDOhwChLjT3UlBcDPfi1lR/yOiB+h6+mZs3ZFiYnV7qiC+FH3VPCUn+ii'
    b'CnBDbirjFDF9Fi1H2n0Sc1R3Su3eZ7pXnl2gpVcXTRQMvWyBCeMdlL1YiCs4DLyfcgT3uqOjINBRz7XU2KLEYkLAMomELEVKGqxE'
    b'5XPmbMGTjUdsLe8QbU+2dr56RZmRyEria3aw/eRg58nBLjuHKMP9gDgTgQwPBOvuZ6x8/B0n7glcXnXNbZw1xbxDVEZk/lqGzQc3'
    b'wLY8YV95+MlgD4Abg4QvyUZ0dvdN0l2cThipZvdAAjVhfE7dnhHBacLyG/DVsD4j5pPokUIY0o0DMqNrIgI9nmJyOgq2drD/9qf4'
    b'zfHRL3+J3708+OPhsXZF6XyKTADLGxGud3lDgxdjlerd5Y1uzb+84YFh6oaNjpZ5JbNSLW/chEO8N2m6Ry4EPOIU2Gi8xFNuh7C9'
    b'oZyh42n3W1zWKbKKERoWc/EQRkmDbUS7m7qCXI1okEER3cQC81jK62rTsssJA3THUcGZyRzhhuptCjVeTXaDf1u1oHiGM8LTS0bL'
    b'G+pxuSXzO9TLaVmnJ23WnY7lSCpWL2k9nHQ/y227aS6a5muacvOkajkt2nlRFV0eLbdQAel83sbPMEwjjJ+9IgLzbbOnUHkTNZl0'
    b'Xzx8nshTgYf9La7IREn3zYiPVGykYLeDetKwMIEDwZVxh8VsGzq3zviVHHVUJdWIy1Jh7SD7+HmDJhsXSbMk44266YoK0n6i+UoG'
    b'lNsoTcoFqAvZqMD/hxxFSVWNTkkCC9EDQTvGrxTJvcBgd3u6xZ4wyD65WiybOuODxUhroOqG5MM7Qh2cnKvssQRiWsCOb26fsseP'
    b'WQTLTjHaYOnxDBCgb9mWs/t8hBJgM227LMqyeg5688dsASGw21+bLtqWIllcA9kianhKMExPAQmOIwH0CdvON2W7rL6u2iKDls1J'
    b'w75hW0RU8JXsAxiJtr2js/sDoxm+xk/5P2CBMUsKP5VQb4EVecKzDAyoIqH/x+1UeT1h5Z8y0N4vMh4pGBp/41nXApqZt0yeab9/'
    b'C+BDWWXa5PTsNwIBGqcYDweso6wnEOWG5WkOtCXbNY3rcujqlm0yFZBSDplvQX7j7kF+c5/VF5eKrg5kYDxv1AXa46dIu0h74iCo'
    b'G7UHy6uuFQCBf9D1Epe1oDTJMtsZ/NZ2Q7uFe+K033FsxCkLSYNy8TVJWoS4O/LLvRH5dKtlmZ8Y/IxRSb3PAoj+gopvAXxk2hub'
    b'gPk5gKwBBVmHfQibgU0Y1/mZzB+fPWovsSRvijqziJnRnf5IiP6mRUs5mOTiiBd//JBpYOozBUh6/3z69JN8HU59afxEWX/wJwHJ'
    b'v1pewIGq4VEG9ognogyVilGOuKHJYgkSFMjbqkfWN/OpCUNBI/Z+2zWChpxWeeTQkGMZy1/udSgjV/BYEeqXbzIPFf6gwyN2Lvfu'
    b'hr7pj3s2ztRjcWZacb1R1k04vhhP2Dml1RQ5xrzTDuzSBNEccXKaRSTVoZFKNHyuxs6jSilVX111TXG2wswtTn3PUtgAeI98neUT'
    b'p4N9ag6LCFFjoN8iyndfP3sthShgnbmmtYx7LLNMwrBWYGn3+OB8Jpr6qGVFr9EZ1c/LPEX3E5SZkVXDuXZdZMI4r0GovrSqN/rd'
    b'Ox99+eG5036GbOdpR0UOayu9hb4H8q4JuvjBN47bTHtuCd8Auh+iH5mJL/j0+G4Ef4tpRkT3ww6Ya3uqcglSTFNK1yesk62X4rw3'
    b'9oHqkP/LJbmUEa6Pj+HNtCumrdPQGxA+210TCfzjNjPMb5DF4IPpOZ+cMOMJBXWxOud26EL3gZDUnAeIZJUGgJEkoA+OZLTWA5J0'
    b'oweO5NLWg1EEoweOKOwFhIoJC+lIHG0WnIqMyiEwNi5ScMySdYBMIw0JSJx2K6+zOEAGLe0CvgY3YcLVgnvj9+hbtjV+IFAYbRAp'
    b'yukHagSWwcaYyqnIwHD6nbUktfq10X02NB8IjkMF5lvnABKiEUKS34kYdb/ChsSbOSpgdNu9uMmhx3gOM9VVNh5dDaqZbVXNfXge'
    b'kEErpxUi6pGAIAW2o3HxvDPANhVt9/CHqpg7JIWQUSLgkJRyAGhoP4Q78dcLkP58zbCNv6FMGa2zSR+9TrxfUB1wW/MqS8D8A5QR'
    b'RVUsVot4XibACxdtp3l38IbrdAmBZklV1Wg0qd1koRyLQcFgtwMHlSqYmtVz4LHBaMJ+j+lYNQcoGJnwqZAL5jBOEGpAQzJGobhf'
    b'tkW8GaLWBGHa8IcA8JBBab3qzOZaga8xYTgdkyB15sxqYo9xYvbpskI8dY1pusez2AjSD/ij82Yp71Yo/3KA2kuu1ZDPmyU9tX78'
    b'GDfJNejtJFnomSHRfwAI/yVC3tdnf8vTbjy+B6uM8yvANWno+P5jxwb3JF6CzaZ3YOpCiYsMdY0hUtTS0LAwcPl4SFBzxQDAITDO'
    b'oSl/hM3m+UHUvk/zXwV9a1SmtefV9Y0INYAFAfkGzATE4hqAL9RqeeOlS9QgHi6BJnBVBXPDnWCspvCwpjVduRTXAt3DTiQc5fCJ'
    b'rpJQiEMVr5CKUcRxugTpxuySc0QAOpkhGxlepeRPysNPyyqWeXuHGioCeZEnWYTYc+xNY1IvwU9l4Ui7upqfQPTQ0U+Zzp+N16Se'
    b'JPC7veB3Hw5+rWSiJzaCI6EwMzTZHiwPl1lQb+J6SPdVtIzi94eLdMJBEsRdMVqr+9DfXl4Vo3Xkv04iw3Fo9k29qIFTQSdMDdq/'
    b'SVzwhXbTh0KDh9AAp0H7t8HgunoJqljOS+nwMFpVvexvCcyK4Y8mLofO/MhvIu90UgE93MsGqS4Ek6X3IrtxGK2P6wujhYY7++aT'
    b'dnZdN6B28a9e8Wn6oP3R/P8EdnGnsfux+6P1IrsJ7M9D+9IJvxigyh79qFJ7fwZjS320wC8BLJUESL2SRYVFwmJo4AwGD126r3+i'
    b'gXN49xq26Tr1Dxa2DqHDpQiWaPGPFMKCWYlafXObzpvliYUCfbqze0loAWSfjBbG02zfWzLLWb9/tFD2vPG+JTzvJY87Btb+Sswl'
    b'19h6oE6B/FV4JSBEc+kH332jVbeq+rayvzMfwRHszq18/w5dCiXYnV31/p35SJhgd27lj+hQp3LW96hq379LPyUU7NN7Lu/VqZ+A'
    b'ehCaGdTJ7tBOdh/UiY9OC/Wj131AV14yLdSXUfkBnYHIW+/nnsoiOieoDgpCGaItIjikDgoDGqIuQkikEAoCGqIvEp5aXjbtgUhW'
    b'2PL19Bdi7R6MZwf06WcHH4hqB/QX5so+AhMF+v143ZBxTVzlUEhfY1KTn0tt5FFNSU2SoTI6L+uzpKTscwJ2ssqKj1AZQYkaL+2t'
    b'adOrFEfSxwd7qasUrLdBHDW03T9SP4Vm8P9UNvUzNP8QbRNG6yqTc8GyKnJ/FOyfhOQBpY7Rwq6pK2kC9TQGq5irofVqJsX8T0R1'
    b'OPVwuzeclDEP1a6FU0WQLnKtUsEYUn87fCSUVeOIYxnuAU3BGPlDgD4bhpQ1oBpFu25+xigWENel0nu+qgrwcM5FCCFDS7OqLqv6'
    b'GlSFxJdis371jGjiqmVofCY2Ldo4yRqcLPWPVpZguJAUVRuNkqyJry+KLgcOfzRhaSLzybEq0W0MfND5lBT0YE35OmNldRXUOj1c'
    b'd+QuGimPZCemFkl9dtRJXN1LUT+NXZQmzdrm3WfXzO3STV3p4MBjqCgJPoIom4feHnxy2hzlMafGvc7muq23TKMNzwSfhLjxmPLA'
    b'c9/5kw1m1raZmiWlQO8v6fhl6s/qhvFeNPtFIUAxFkNELHQUUQZ0kgGan/7F42kmofBQhBTkjq8sm3lW2aYTxi4h0NveQzIYV0Y2'
    b'QK4covthHbwJAZyS/8oDO4NbGPtCHMlp0RYQRlSbUU9Pzqg+okfPWvCTS8yL1EGqF8kxMLi/TcN9TRgG2yzQAHEiGKkI6MlmgQEv'
    b'PPWS8zw+D3z/NfD9yve9zFtIMnXdXcS3tR4rcZQvQyUNxEdc5YFSgokcwG6o4LlRsKgXEGXQ+gKx/6xPEM7P+gQR+vRPq7IrYnDy'
    b'EhvjzLnJy4SHKWvy6ry7oG1vzXiTI/A9gkCxiZ5/Y7S41D+d+o6bpvIG8fQUXGgu89uW89Skb5aKb53G4U5g/7TK6bfKmbDRqoIk'
    b'nucV5GXY+AcY6UgDGFNg/nnNYYyuwrYxZjWfocwDDFV4EayYsidxrE+8piRIZ1FDBYV8euXPHtrsP415Cg77gRYqYuEEmE9up4JQ'
    b'0VRle8ueL1DBWhgOIKLCKy/o5366yBpHU1/b4ez8qRkeYDPyAB8XRa3bJgxq3l4hpl+yh/oqvsZ+hUEGMfV8fYbXWXBB3CBDqGm1'
    b'G0JEMkpctgKd+scrxjqwS3l8BnSoZglSamXqPmCelj46MNGpr2ceznZRQGaL0ZPR9G91AZcCD3aP4NSgSsP7EiSGg8YyqgMPETq0'
    b'Iw8tHO6wq5fbW7TfnAyGpZjwpZBmAh6e0OL+vNdaIA51v0NSYfhDlEkCJI2kcREf4bc4KXmqIU1UrS0LCHBc+TRiXupDOymGnYLf'
    b'FCI0Clg6ZxjypqwdhP0A3GsITX19Mke14oe0Lu8oYx6FqZVLpN8P7WvQMCbQCY6zpyco93SFn4f15TMZbOprwXr9RxmE6NqJQUQf'
    b'v7KOjuFE/HcNA/qZ7EpkPglzfCfWz7Crs36PgRJTdhh8yNrkIQ6i6ElqgNDsBAIPS9zMK2h4WUt6TDCs2Nf3NwsZZBKCd8Z9WYMq'
    b'XrvqYAXvf5gRBXbkpxeCnfmq37/De8zOV/1jZmjSCmtnSNWHdygeYz/VJ0++0NGbtSDsOkgitwJQAyShBdWutQ5qmGK0IftqDoE+'
    b'bNy+muugh6kqG3pPg/WdrKOsgp2FG67r1KAzAXPZfWgVJmw0Cp1EL7Hmg+epaMNViHcI2QV1lk0+LzC+IkYFBYiCKhhZmSDh7zKH'
    b'x3A++kDt7jjl4NQr5lgVaCFFBvlzqBMpAmKV+APk/9PIEPfyX+a3PVfdDx9tR8x3U6wppEoUdio9g+Ot7OEpyGYkHf27jzDymVIq'
    b'ouj+RhS+5+i/mC2Fbk0RisL4sV64qkTaRQyxuXiAK2+f4cSAOJPRA40raJHlWR/ek0g4YXco7s2gfjk5qFl2oO144KD0a+0faLHg'
    b'o0iHDEJO3xqGk74tOBCqaWZbu8obUKRw6SGyyhKyKes3UI+ZT0tXobRx1+n6C1l+3oCh4rKp50UXqlMv46JK60UeqlDhre2rUafz'
    b'UNE8XNSjNfIMrr+eNsY1ANP5mhrztTWCKq21yqu1SizPxHugaLPuqQVT7ime9xfDZPtaryqBTG4BiTSQs1WlbrKamALvJ+yHo+M/'
    b'7x9/Hx8fvnt//Do+OPrT4fH+j4fxwdGr9z+/fmupGix3c0srq9sGiQHJu+ZxKndrl/kVGnVSm3W104ukwls8sDqs4dDKChsPq5/l'
    b'y+4i3r0dNk+q/dxTm59qjsPwYUANcpZXaU/FLk8vKnxL+vXNZqt2mYD1kBiVm2dvZIUB9u6mEMuAPS6RJeijP1+VcsKo6msxk5j2'
    b'hXfPx6QVcKKubuJlU6QQ1ba8FfpBtGZBEQ11Fl3tgYQIH//9ShM/QSTytqhazJ4BGbCMwMN+s5Suia6mQEfpFCvRj0VbJdGVv50M'
    b'E6t9u9KNb5CYgji/SCFZhAuj2SATQLIvMLwJBIXnA0I4yvwGHsukLCPUcVGZkG9KvZjqxT+JQC74ISI5+LuuG3Rn550bmj5f0BJI'
    b'5lU3l34GBEqGhCLx1+vxlcb4t/ltK4V+OAYh8VNLNGEkXxf2aj6JH/xd5rcxkpxshnCtU0ddYQXOb9CnQVq3dM866BS+N+Wp0CBL'
    b'qz5gORQrNxrwSZjVGxfQENK59QT3KqqSKbobIg63VNh8mawkzTPcjzyQ6hlxuU+pr13HovLMBC47mvYdA3ve89GH9I78Nw1JuxFC'
    b'Cn8Pl+PbsDG1uwMdc9LfG75cQ4OUdVdI9S/fMTUCWiXZozZTe+mRUhe7KRV8Rm+I/vV4Hfh02a+px3riHtFDAuFCxILgrdCfoeB6'
    b'XN0J2aRcDGwHcvcrJ8IXFgWm7cgJZEEoVQJPYsx9I9HoT74OxDN53EVFG27iMaRRnyBgI8SSadE7LUvEPWkRCgYIhvkmvI8Wa26w'
    b'pXB44IddSecCNVTiVPPef5Q3KGtau9H6MLAGNHu2fI56J2joYnzwx5FVgMVIJPA5EDRioHj2tNSapgAy0Mak5QM2y0It5Fgtq9Z9'
    b'wW/Y3/Vh9Vsn612Ng2bIZOhpr7FaqMs8X7rsBK6DfajNUjE28+vrZOEmecZseutSP+NHEVf6ARsS1BgOqUUxoNbU9PICD7OAfYgV'
    b'7P0tYU/ZE/bTy7fvjo5fHuy/ir/ff7cf/+/v9zEdMecx2RNLIvPEPgWLosqbq6Iq4kUNnNRqESclWn76xqd4obNylS+bAtOieiqe'
    b'NXlyCWNv8261lI+UP0u4NOgV9qR9fJbVRGcBe9ud+u9E0BJV1lLPtok0Hc1xlndJAQ81x04SwulAot2A48fNRpUhZLzzTq+B4EpB'
    b'LErPrDCeZh1ydV7yIWhHGLzzrlmhd1HU2oftCv27IgDpkn5nysrc0Clab35oLdDGsPH06A+AOtoLgvHZfIiEvZwSCsYHlWRPsIbR'
    b'G9dXeJNn9momAtmNsIznW4asc43Nvq9Ra4hMDHtWAmKurzDZPp74DQfrYwm538kczqoxJv3yztuTEU0drKohXjy/Zzw5D8hVsnye'
    b'rMoumrcTpiqr9gK4vLHrYBgNFBzP3V8HyWoiYA3Umsw5XbEsMOa8jHgto/nLydqDdrvmtNyy6OKzBPxzlkV38m9RBP/RV/gbKrEW'
    b'DTxdqKq1mKK6GxTmVNv+kxH0e1XU4OSAfiRovaGx8HxcIrGL1qq+9FfEJEd0hPKbJIWvVUWpNpTIj/t7i3h0owZdOvD7Dv8Hum9g'
    b'DdNpA3O9UDyLifq1a/wKtCDQ4ifvQEKQjUi0QRpuNfoI3AqqeFm3XazFAuVnJynL+lpLHwChpTOZQh3zjJjEDxE0hOOpQ0onK9rI'
    b'fHIzMx27PIRS61XmyaWmaFJkTWpIpPAN8fehvyGpUIr1z0g2Ac4qIpmgvt1oOgHyhXTadknTtZAOL4I1JQET/AsZMX2V+SkzT6gY'
    b'qzZNGDOxNtrUjUaigB9S5LC1uvoh5apOsjBzyQYqHiL/cxJmoeWyDt3mf/ObpfDKoyBGeZXFXZPAqxpnyW1LBnoGCAzvJsTHE+ap'
    b'AO68ooIW77TulFW/YrPMtlL0pmx7JYBF0bZFda6AYAXkYM0VE7MaQ7IoT/l53UGmWc+LrrrgMl+xnXXdxrxQZHlEyTDM3nAKuJEz'
    b'V4lDeUMPRFxzyRZoZ4U30Y+JaCiTHmnjABwovpuJdnklsCUyMajIO46GNkpC5IeCMYZEA249oQVYMQCngJ/OlpAydFVlXVMs14L3'
    b'NNGAOz7lvieXTh1WFeI4EXrW90B/owDq4EEFE1d1Va3QCpykYLpljTKw3XNx26v9d4dv38VHr1/9Jd4/ODh8827/9YFUMpoksaCp'
    b'5zIBkyvH8w3qCW32nCQ1+lQnTBNzajljJEbS8a5oyMGqh9TtcgAU/SX2AKBDrEORLv2UxxiutJD0xZa7v6R1HvFcptvPNw8YmIyp'
    b'1KBfjfco1eeTJINEb4ZLh4CHr1jLrvOGtFiP2FlZp5dw3VXu0PwG/s3O8jRZCcQAydo3mTUsqFIv8paN0lXT5BWyym1XdKu86tAU'
    b'4ub2iRkbQAJj7PoiJ8sTTuSp9cgXZ3nTXhRLNi/KHCSMAicBOwwEf5U3LE3SC055E8CjYzbS4CkwMYCxBkLdFx17+Raevzavuqk2'
    b'06OmOIfgQ0x7N3uAj8a0rWyeFGWesbO6u9BGBjH9WrGgkKG+u8jZyB5Ru5rPixt9FDxjWRzouG5k9jcevAIAV9Bdmmda//72NWAG'
    b'5BqBPZEolbS3WpEGSAxI47cMjjkWZwdOVesKiw/e/onPjwM9ztu6xNQXaG5ZLNn+98cMUGyZ3LKzfF43OCl2DEd78wwOf7tqroqr'
    b'mk4ILrtYs/0sKyjOARi27X9/vCkgicPVsqTJGex30qQXm3AdWISy8f+fvTdZciPJEgTv8RVWYGUHEAGA7s4lIz0DIeLJ8IgKKQYZ'
    b'TTKzssSFgjCHKeCWDpghzAy+JIspfeg+9MyIzKXmNoc5jMiMzKnnNPf5lD52Tf3DyFt0VzUzOJ25dKUd6ISZ6tPt6dOnb82vRMKn'
    b'vtxrwFWJm+06X+TN+jYpt80Eo28C5BpTC5e7xphc6mSip/iXCXguU6LCBzgMf0UxhAoFOrgQtZgmP+wqHq7VKcynlIMBkgRXSmgI'
    b'GbdKWidpstqlVZakK4jN0dizdZ6nNU2Wsd3KDB2rgQBBOoIweaI5mV+k6Bw2l/MK0U9sLM6LAGxdeXG7WAuzOr3YrtPbnlAKyHxL'
    b'9TVdM916IxXhmVZiu04XYuhuPrThDRULds8tjZg7HHzOL3muKPEyoCy41BkrbnYWBPHD4Jh0A4CHwSLTvtTJ6JZcXxMv5oAX8+u0'
    b'KvKCGCHYEtEBWHDCzcpciwgMx7hYrqb96Znd1xj9csLAQKf3a0ZVLauO4cpC7gbA54FFtWaKvuBxm/zX//DPRAeQwi0aGpYH1d4Z'
    b'CPUZvEoA+VqB1+kGKMs6vUEBAi+2ydNd5QJcgJb1WVhUo8V/jZQOR1g+Uo4ix6bEUHYjBQSwhVTXTPQtmXhdpNv6ojSUYJD+RP2g'
    b'1N2ucBEA65eLNYSKMHkszm3OFhx621ACdggjBa2D6XKaVyhKNAplmdVBjN1llJFnASzwIq2uxARovma7fj6CTHd0eUlAnVxLO9Us'
    b'KYvkxcsXE6iK2eaA5dDg6Chi3gPDOl8IdU5NqQQS9aODyTcQEGsHx1pSl1DwNtnu1oSZDzA3cZKuVpVAl8k3b75/CKJkRAbdOTBf'
    b'Ja6HDhdj1NgVBnYh0nVzcTtN3lwIY8Q5nCxFOSm3eFbB2bqshO5wnQzXYpUubkd8vsAmASEubLdFeQWabEzQDu9Jmwef9T3dq+Bq'
    b'iw1k8K8L7LRstGYU75EpFPWWbhc0BV6UVxK9Tbh/cJpFNYHzzrTvMOoGLt7hRvBz02x4WFp8t5DeWbJem4mHLOPZecgPAasHdad7'
    b'9uq7N6jTe/Pm+7DdKMnOFNL9OfT1NyfPf33y5ruXL9p6DFu1EheiqOFK9yfs9cvvf3h1+nenL15/95vT+Te/fvH1yfenL96cPG/t'
    b'vBQ2VHmDhxxjibb+4Rfh0tZq6TrWa0eoYU6Wrek0AHhz2t1Z1x6LxB44wyjf4rJTVpCB4ApzEfCusOa1xzh1c/oYCjds1XWbt9Hd'
    b'6sRoz4nr3yNvdt1e+Sjd2jNuX9ws1rsMPNgztglEps3G379hGa4mTpa3iyRePWJjmge79hzxwXTpgMyu8IauVEIpthEMaJ+s5rvi'
    b'aMLUubPmVECXL4p9r5FYdcW1MlMfHIrQDt7WCmngOjJIEPYnPfgXuGTnqyKBvOhgEuVzHWPkrQ8PJn//8PBg8u+l1EXyIvVt3Qgw'
    b'dFggiwJCkOTZy1c2Jfv+uxffff/r7+fffHf6/OvXii+ZJv9AF2l1S85r3dMxoAHcfo+eEkfUlMy+gJy/NrgeXHTwIU1EUe5WF0lT'
    b'MkTsDjBXGDIheY2epqvb4wSEMZJBw+o4x/IuDmqaXbrGWkkmFnmtEhk/SMgNDmdVZm+oxTYFyDABYKOY1/l5DthKDBHzFp18kCy3'
    b'F/tDLMfduB5uMKQKUGBb7c+oT2QZhlXhqgpQeR8qnDz7AwEkJUCwhFlA7gf0p7awn0qFBLwSqFNBvnZ2i3ytNksQlLuxFTBnX7vQ'
    b'nG0tZ6XP9jZn0Omz+SnY7/Z29GC8k8Zs0xlaqFHrQHmQfAvbZAcXgaIs3C2F146uO88v1X5dr2uUR8Jup1tFci4u0qscctk3ZZOu'
    b'DeAjBR1vJLTbxHIJFllXpjuuNea9VkVviGUQK7/iJZA7qB8pD57HkaOIZR14KOumQoP8ig+I5Qq0lCiapRTLISFQkBcJttWLf/tq'
    b'lsh24bNWcFMxS6C1B59mgNWF+gFvm8++8+HKxTonj/H49a5apguBHFla3C7TRVODTUyaLCtRXxSirkl8k69hN9RNuhYT1GrgFsAN'
    b'kNewRRjgg8NEaRC0bWZCxtUPk2cn374iKIOkvt1sm3JT481kXe4y0JoArFSeswBnMinKyaJcg/FbWU2T7yBcbroGD8fFhZjvapEl'
    b'XyVPfoYqC9h240TUixTIPm2zxRLlK0DDMR4N3GNOXvzjNyfP3ryev35z8uY1z+9yTtsWlVxDWU3zrhY0SInQpKSQkzWdAtRNg5i5'
    b'n/QIBm+ThwoMsciyNzadVhCkkjsIXn5c5Je9IRv3AIkIBE4OEX+0ll3beOhsTtnsV8kB4X9kor6CPj2JXFFUc3KId2rQnTxo8vCO'
    b't6KWDux9tfoyOZj+PDR0pfiSglV2Qoy22SY5hwt9L1rS1hHSwLX0QFp+BWmeaXUTLBCxuggDi6m6g6Xjcvpg8XYC6jB2a85CgDsm'
    b'NmOfWFryp8mVqPJlvsAT45gIpJKHbkWVKEk4mf5Qi6bz8HwrjT3IKFPHooWjSPkWLutoNFrDSCJrDD2bE0YTwCmzGb3g5AzOkikj'
    b'q5rt9B6USjllgr57pjCKHeRb23rSo60nPdpi5mG+sVuyQiyEG7KK9BuTv5ZntBJ+xFMb/HGCtjhS/DTfjJNHbvwge5JlDWPd2us8'
    b'ceo8CdRxpH3hIc3rdLNlooFHMUmLwoWneSM2cOyeTZ4es2oXNhgUfwQmXVcehmm/uxhMeZbblzdjJhxJF43ak3KpfoBh3SNcdN21'
    b'8LHKTazLa9MeDBiNQ22ApoHky+QGj4MjR64TkzYZce+ZBFgOdXT/dawKtXOBvfZ7RU7YK07AXbz+e3v+w2NkiOA5WHQKJlqdd01h'
    b'RS8n3r4L5Xr5+i4V8JgIaHoAS7SLeem6nqHw2M40LR6xvWas9zgHFnC6ARL2+5Gc4dC5HFEkNkO1ZfnLs8O5JUVqGYwdYgQeP8GM'
    b'XyTm2YsfkYrwQIaB70y5rA/sKzFE7TGcInA3gml4KD0eDM+Q6e/qEvLeXFc5xHATN80Q3kyz3WZbs/ULybeKZnbEZzF7sNBX6XcC'
    b'pkuwyWiv6WM/LxpRXWH67u3Qc0FxfEHyouF9RYYHXBeMkdObITrmiyZtwDBnubIcF3Qz0rz1EHCXs8V6mVa8qPPH2IK9pb3mXA/D'
    b'tuatAbiB9g4Nl1QrZIqZNaBXl2wL/vvukJm1oFd3TM/Ie+zMe8YyNmKI4pjUhBBnGog50uYIZWKqkSPIxk4nQ50fqAQUCoFwIPkS'
    b'vkRCBUt5v9kDkn3qn2XVf49xuCLDyTaZYfOWw3W3126PZA8ANRS9gO1F4lkePMJX7sBnPD40g5cxejuFIasOr9PNeZYmN0TXzWmh'
    b'vApNNbwZje9OTJgAqmHdHZAcfl6wrsFABcL1uTQj5uFu0u0cLH61fanOsmRjuUNUdTorM2KBmdFKvYwnttJFvDNaEldiBlVmEV3j'
    b'/rFOw74f3PPOB222RfMwbC6rEcdAPWcDeKQxoB27rMbJ+nwtg9OozoV1TmOeIotJCrbHESRCX6JZuiSl3IgK7iNp1eRgaOZuK7QD'
    b'o0WhCxOkRQtQSkZBK04P8ojsIOrj6LGDeVSuSauVaDTqhhrjMtG2sp0kffVx8l0jKpByYGiOeyfroWiaXqecgfIew16iZvMdkRt9'
    b'6TIG8P4j0HueP70UoF3tJiLu0rDzJ8j/qiuRzSkuBPoLKozFnHG4I+jCQGUC24I+4EVZopLHtMq0dJdVzyx0KDXzxoVkJrhbfM5t'
    b'MFIJ+2i5LNjhLccVvFnmbSfXXmLx/cyahHY/k+b1fc85c+brvYMpUqnBKVV2m6GHRYZ9jomzi7S+UBXVmKFz3oDIAmXkzrfftr8Y'
    b'RuPJ58gEGM0bli2V2KQ5CKa5Il8/ILdLcjg9SCbumKW1zeY8L6wd44/fZgm9AXyVHIrJIWkRvG7wRyNY0SJF3xSv5EMPchuSBWaK'
    b'0c25iDsDRF9HQBZtDcBAP6OumaLb+kLPJqdoDy2AXdUxCQ0AcYeuptYs7E2cNxIPzVCwrkEQssJEuh1ADZ4DzsVysM4z60o9UXpe'
    b'D60PE8CvEfX3i3h3PYmGlGaw+CZ5aLXnhwyTog2v4yGBgmn6fkVMCbfDPWWFFpEEeytYh1E3e4WlfVTVGd4CZD9AGfflpnqQ9kBf'
    b'fGrq7Rqm0pxAxKCfkY2lYZ0Fe4q3Hw3QmWzN2wPBakSVEwBaXIpSTpls5tly7C2+5STuA3XvrmyuBf0kO1e3fM+ETqY5FvAz7sBN'
    b'u3O3jXhaGbD31R20b4n2TTEw+dj1GzgC0/piIFfxRp+0s8BJS+LQlnSGew6kKlmBsc+w2wbqjgZGwe+w66+fn57+5hQMFV58ffL8'
    b'5YvT+auXz0/n35/8YF2e6W+/YYHhak+RjV8ZbWGRPVfM7sz8YQsjQ9UdBDfeGHucb9sFGE5SVtVSRR6FfzHM7jhha9l5el4zncWb'
    b'Av6PNkWVgqFunS7F3EhZZSdz4N1VbKd5vcyLvBGQmsGgGASE6htNaoPI8xprQDQVIL1H3j1cCuT55wRqqOQQ4DxP492kRbrC+arR'
    b'S3Re5fXlXNzkDXsQERphjNbv0+02L1Y6Jg9HDhJVXkpNCU+KvBZudpykNvB1K9LL0PvP6M8FqF9gFayPTZXmazjn41/Qwgsjzlvf'
    b'sxw8zc7Rr3beXIC1UbnOVBHjwgf2Baa8ZDAYfM9pKOQ0TWCaMGZJWYDVUJac30rbWI32MpbBYEA+3rzndN4USRUhV0orVfGWl01O'
    b'aeNK4GrKQJOHB521NoAselZdiOjelQxUAQXVmnKAbCjvq/QaHK34MilS8J4eAnP8ub/4o+QhMtD02Vj9MfI5EJPj0NAiAV/sg/9y'
    b'5vSHboFOU8lXxNf7KEHsZTACNE+ABX6eLhtRcV2aEdwbuPx0H9BsuN7yaoXBU7oEG2neUpTIlToxbq1ZN+lKHKHro7hplJqyV13c'
    b'w3vV0AcJbIr5tlzni1vqMwDbFwgRkaKpbufo9R4auKJlZu6J0BZNvkwOp2SkBA85oMs1+GoWqWWVD05SjR77a1GZwQi5i6gKZwOt'
    b'2E6x2sURZ2KR3hKWONsUejSQuWSkgY4WvmjBFQiTkn8KZY4hf84WiRm5Qld5Jgz5Fki1lFCLOhaRSveqnWbpFveZqsyoEqgMZNSu'
    b'zcdtoCwM2y6Lty4e2Sa9YTqdzIBGMLW2I8px8LglBOlpyvliudIyMVSCQnhmkHDB/40YVeVqOCDTqCfHGEYDPCtk2iFNy1VQiel0'
    b'OmCWG8Ij8bqYN/pATCY/elOvwE2qlawz7RHHZLSSLxOiUgzE1vRHy/wG07laCOHSN9BwOHSzC5XcC2R3DTN0slUbedN9FCyaM9VU'
    b'i1WKo1Zc9kMR2M2qerp9UYAQGoLq4Zxat9DOLSNVMJ9YQ8WGO+ua9ut7z68mbC1Tgdhj7t56KxZgP+gPX5pm2tPVWc2etT6tdJch'
    b'wVmfyVAzz0AdYbzGhD3F8LwinV21V92xvPPNEzDGU2i3uvZ0rhFB74q2sr9Ptfc2EnYOeU+8U9RIh4jrIKQ6O3QsbBy78PBQki8T'
    b'8wKV5rVIXu0KAH8KFHk4eCEAqRoI61c3SXNdyl6Vy+Tly9fyFED5kApl5gRglGOsLbQ6i8+w5WJzR9KJWMUT9w6aMjVRneQULeCr'
    b'vIa4z5KyngU7+xatw7iBr2bJ4XuHNHGOFnsmDEwITFLr1LDMy0yYaseYNHg+Z5wyltxchpczgspprD6aHoAUOgYFIhDB3uQAdWDy'
    b'WecZHMWomDBzAwV6SRDNtXALwZQZ4oEbxgbt3uQPwxKpO/CkH7TdiGW6h3Fz0Isj3eYgNt7VmQUyOhehmnAGH8CDs4ECbSmojGuT'
    b'tTGpLGTKkAIperoVzz7IjWjSUHRhtfIDyVAPjpMDwwyKBaiLdKuSAIMLVt3ADYc/btIb03LK4GIBGLCummJyyFOf7YrjPdYr4EJY'
    b'Ly5EtluLjEIfbrPpi/RN+PPcTJ1h6CHx1bFZ1U4NbmStt2xoMPb6yBiITX/reZNeioKzJpkm/UbOJO8UJetG1Jdzvw56d4V6AXes'
    b'vFhBsMjrWrdUicZ58yB53ZTbybqsaxAmUKg/bGsrFixIUJIe8kAyvswXuw2IGSLYi+7aKNeBK4qWTKgkWzl4VuDdmHddud2KbA6m'
    b'ctFkIxpoLSughRn5hUNAJAVrDsOabxdaNeXsVWMkVnmkXEdP+IB8kEw+9HGDM746NFzsj0bHSpCD/aYwhijjAScUjnnOML4rMgFJ'
    b'ZsAlsFyGViMZXl/ki4sE3JRoUWsMOmMUZVgUCns0Td5QqZPnzxOD50keJhbrpBGBPfsZjN15EG/nok7OqzLN1rfT5GsS2iYvv/kG'
    b'/RlFcYVO83JS/u7k9ekc/z18Mn91OH/z6uS759+9+HZ++uLkV89Pv54dotvUcjW15VHMQuHdjWEhGYF9N01+ENWEN4wWn1zlaQiQ'
    b'YaK5XUgHSHJbc8va1qWAW8MDdKlAD6PMWDAOdHRf2DPfHj6pDuEuPy+L8PUiOD0DvvUyMjMYordALAElATu4+HCAbw6fzKvDuQQ4'
    b'UML+mdUNC6Ro22qtE47b7VBuNwa3vO4NzlsTyXm42+5ZIm4a8AUEby/nQuFg8XBT1sDjFjlsNEDbNdt4PEiooRokJMm6LFaiUrE7'
    b'IdzFp5VIyl2VXOSrC1E3k0VZXOUkHidHa46AxTO56D1O19jaHakqrTQY7fQ5UkmKo9tqOTqStkuvFoUGKzn4aZfRUvxZWB/Vrykt'
    b'yB8nk4PpwRck2vwi1KQtUv+gZi1Q1PThE2z68Elr01pGr/BC8SSt3GdnTzRkuemMP2zsE+paRBx9P70LA8cOfkE9+6Kzg2i+aWKs'
    b'i7tx5AUBOrJcymTqIFBM76lA0Y/BIhw5LAL0M0lVryiqRVqk69u6SSoB8WRKiNHDgCTaIjf3AqLD1mKxwzccR948mD/CWXXUelbJ'
    b'Ds8x9RItQsuJddTrxDqa22Ddc0t2yQJcN9gDE6nh0oHqOdS1t/fcmFgtGDhSsfNlI0i7/Y3TCtqpZNF6tygOwsR/1lcwyn8MBH3U'
    b'gaAQTCK5TuukBDYfqClESWL+/AFoiSEmKZPWShQr9DjfYH3KFXiR1nxJACkWcPpNCbGzm3KTPDr4mUTaj4vHj9rxuO6JwY96YfCj'
    b'uQTo4q7shgUSj+rtooGAXEZwvMU638bJsOoyHgYaQojgSmmF0SYsxd3bxNpNaTb56GBk/LGa1F1Nb7hKG1fCKqs5xPdtQHIqlejG'
    b'yUOKeflhkVeLHSTFgVYg0YNcIy1zlZ/8zdt62CmFvduEu5/Nf2nUsqQhMek/09F2TfmL17I56bJCJdDV9/YDxyvBBIf7UYjT0/Q4'
    b'eTTBDPLKbkKOCkR7jUiGdOt89fLk6+9Pfkj+3//jaPpUXdi+3qXrCYZ1a8rVak1BlCFkP6pUMR77yYuv8R57lVbJZldDNoSkLKbJ'
    b'P+gQvuVyOZZx4lCKkjYXQLZF1WCYOvjEwasgIMpaTGyF/QPV5fS8vBLJ8Py2ERNw68Z4SABiW4kJDnnyNL336ybAfZq2Ej+15nKt'
    b'N7s17NErsQ5rtBRUUVwR1AgtfJpKmAYd1EpaBUftV4qT7nQaA6PbTbIeOeOac8KSWXIAUwc3+aKU8z5ODh8ePYR4B+s0gxsilpX1'
    b'mypfrSA/pkFrAAb/JriA+1UmMmbWqLP0CQ5GEFlvWe813z5NqTeaQthS/H02oVwQAnjoEh11AUJ7o6emrP/urRw5rZiXi/tr5ZHT'
    b'yhG1cuS28tadVfaocOezP0F15xQJ6nJdQjZZ/y7FFHV8T80duc09onYefZzmHrnNPSWazX/s5rypll4Y9zfXCBE78gvqAf+5/2nW'
    b'Lf2cmuA/9z/DuqXH1MTjjsmVJ+n8fLdcCggUdJdt5EAhgvBoZP75aAfz4ji5wjSGECSCjbVI5NZ9KDtS5F0t+Og1UrBIP6wHKLnV'
    b'TTHfg7yhITWGY9yXQj99Nv/Ny+dvTl59e/pGy6Dv93jleJh2iia8RBVXE6nFrifAbwz5xnUIHEQjwEb0F18cpCL7hZRv1mV395NF'
    b'ygcQtCtz0xA/k2+lRBKPykXrmd82qd69h+F13XyeLuZX5VrxpvreY/VHAn26kMZwV+W63ya4KteyDoUszn+PvT2YHh6N1J9DMXms'
    b'uv50MV+X5SVGWdQSAV8cAKBlQS0AeIqpFZ9irBgDItLT/rw8wEYqYRDiJ0Qk+I9zQYO5EiTFvkMjXBXU1cii07+649bNTCwoZwZo'
    b'8mpWcKr72NlbSy8kTQgLAZIqrEHxosp1skjXCzYhBCN8DChH0WogQQLWVB46Aaf+uqks5yJZ1PDbR5AQt6uZp2tRNTLSDvs4qRrB'
    b'UDusqhywbjYbaFEnpFeROSGz5VmsHcMEx3LsKTOpuTfaAZt4+DLNIXXdAZmSQEfxJY2JvGp0h/TkUV9W6RZDJ1U4XUrjPEbVXu6+'
    b'xlnMC8P/irsCqE5wprcirZKJrI8/wS3x8Cj5POEiFANPl8Hf8hwhdxLlxaRuC/nNcJveQrjroBs6WCO8xf4FPrJU11p8XNEa0lrB'
    b'1EjYJAsOG7pbBkIgbmNLT2O3MBSZhZEMo72XdkwGtvRQEmtkF1BL1QGfCnkt2BZsYfioVOsAj2U86KaZWxi2lHbjDH0uh/I5tWmu'
    b'ABUkT5wvumfcizIBD02yzq1RCem9GTbsU0W5W5HCNHZZlmYrUhQ9SY7jBNRefSgckKWYRoF6F0jLG3MPONFJCLP15GFkIG4SFVLB'
    b'jeQYlFuWlxYEGeUELsfGZjFNgoI7pl83TDDsvUEds92pB6N+HdQGUlZfGKbh/CuRBudfIwb9lEt/MD0gQaHak+DDisYkrYEZ/Hh1'
    b'MtgA+WP29FcyH5mtz/voxCjClHvhyA5GB0KxCfzgaNoglaHPPNvYYF/t2T6Ts/sWEq2G4zbIR6xDbVpmtb1apAXs1aDpHt8GknwE'
    b'2iH6IRRsKK5XuzHRRvAChw4G9pIfjM+ng5H+hylYjEJGV7IDjE07Y6vTASRIVfVea4ltESar8nnfRUla6ZhBOZ46pOPoiUU7DuEn'
    b'D8KiJHyKmYCJ4gN5yYGiVGmxEkPTzHqSHFqRf8luUUf8pXJnOUdfVcaM8ZLJ58mhUXoDPujZWdABZ5boPH66D0pQgFlVVVRjWq+h'
    b'o1uZODoV6dFov2V3Rt2IPCqQTYb0npqfDknvWfAK11UWrGKKV3BoYN3EBaSWqUSdc95SggRi+ORHR0r8I+ADZ8HNaymPx0SetSGN'
    b'N8C4cnnZ/V+SPJcS4BpyfAK5Y0NJgrErFhew+pkrwGfJBuOt01cbZR+oIynLKIcrKVmvBCQxOhcVGKGRiBlVBTT1ebGoRFpzQlgN'
    b'K62lkBozaYymCtoE6Vkmp32TXvLMbFIOfm30aC1SsAlsLtLCnANldxDEJz1meIxReQFlXIRrQy+b+j5I3pDODHHoGDuXCbEFjzW9'
    b'lNcXZS2Sr79OriEvo+DszvJhbkVpB1zybvT8q1lYdn925ATEDcB99Il3WvaBfNgN+ehukA+6IR86k31KGR/Qpq4A9VZSN2JLSSfL'
    b'AmYYJx/W8pdkk7oqkx2LnIwptZr5ylXR+N3ydTgmhFBxT2Vjo5hXJaocVhan5uOStuWA2xMZz/M7s4PvB/4KuUP6ynQw1zP+ionf'
    b'sdzHKAaFV/VFWQKSQ1ZobJuVTef+4B4kPzqS4B9lPu1rQUuYrikv1nV6S8vZlMnBNADph1cvf3j5+uQ5JFDjVAu77Qq8QurpJkvW'
    b'eQEWI4+QjGBarWBv7P0O3szekn2WDA+TzxPq7+hHnxd4kLx4+QYykUoqpN12/I6DK1HPRtFPPySED9wNIgrGWLmQIjF8Zei2VXAf'
    b'77jl3ptyLJ6JXrinXW4sqwIp1nS0bWcuzElyaIeEDrPrHa2Y8bVx2/gWGl7nHyTPw6p2OrOH+pQG3cKl2DaJfVo70EDkztwKaiQw'
    b'e04ltlWZ7RaQwQpSUVXojC3tfY25jqwkXHjDXNhXs2Ti6m/8edsTQfoiB87xEEMgBRsYtXT8S6PjOtDIPVNaTWidjrfjUcjMJr44'
    b'Xmh3H3f3wNtlWS10MZ1mRCZDl7cimlvb1zzSQXC3NCfGSv6ul3bUXlBPZSiekaznCJvMsJq2YKtjPi1hYJeWkKxrkkqQ+kZfQAwI'
    b'oFEYahUPedKswVH1R6mk+TGkjtBDfJCIm4UQWQ33B0vV9OM4qS+qvLjEDHZoTiButmUNMkfjgMVOkEZlnJAnzrWAkhUk9ALuvcBz'
    b'+yrFtF4IB1HEvMD8CqyN4OxVFkcY64M9ZyyTI8/6ER7ogkY+GIiDgPrKodRzMiGxrdpBF1ZLHWYjfROiRHKNLA1dsZ3WTeaAP5vY'
    b'sCGIbFYuZ4egYIAaP1XN8FDG2Vc77Qai9ien+Ac4z349GBSpm3HA8S01q9HeswAFD0W13L45vPlIiUfwY0izSTces/2xWyYialHQ'
    b'SG3XXoa1fuFSvoTNf/MgOWXkhl7TFoEESi2oHuJqIaOGnMnZwfTnY+1k/uiAUsxdYCyIy2RVwr20RIA+WxfEfVvqRFdMY586mlSb'
    b'mjvxV3QGX/u9JdEOU73YeeG3AEsf/T5uPWqsfgQmA5O83VtP/Ab2C/rgJY2JHI2BC6AOHg02ehDSIO4X66OtIRbbBVkN5HuQ7Qkr'
    b'If44fQgxyHardgYh+TiRQ81H+xKPE3SOBqliXrR5SwfDoNrhUPO6SIcSHHIZwwzTjVrSSlXAB/W2c3qQNzIGb2xWb54+YGXcZmPM'
    b'GgzRwg8ctZwKbzajc+KXNDSvIFm2j26IXOC80j3mOHwziIIkAXLELWO5rBF6OxDtDTZudFP5bCtxNYeQjFp070iS5VOL9ThZ5gWE'
    b'3R1DBMAU1nCXrzNJQZywX+4DBirBD5tN+D31bcZdBLyk/ylmM1yNInLCVANHi6Zh4YJeeLGZ9yZc0WGYZzFG2rjNep90SBMOZWIX'
    b'CDfs0OtZnJL3OOkZN2qxZlMUjHxMCxxRcxrq4KiiC57PPkPFc/R7Wx4UDELx7lKmrrLiOYf2PNOy9y2tGdRjcJycteQteNsGJeYT'
    b'QdzA4Jhve+Fr9V0A44UO4Jq/+wDiW7ua3sFx+EYfhmVr1eWDKgKl+G9dfidcd/icgcdcW8a81rNp33Dd3aPqw9RQwFGiPfJaZZ5b'
    b'yZf4KoCcEXliMA7MWJNg/V8rvnj/nCexJ0Zp3U5d9yume9deHkgMnSodcC0Uay9rLEAH0NixIx8rAHNgEeO140gaOMKXA7lymgt+'
    b'9+n40+nvyrwYciQrE61GjlKh2yoiFl9or7RiH7yIf4r5VogLnIyFRZ1V9s0n403wXlgwAMmEhQQDeRCb3I1W84dxoOedtKszvndf'
    b'a6uWfJ7ltZak+UNbBwFBpG1mnSVbB6lXrkxKeR1eBmavsfZnybA1ythDCuxlmkqGh2AEg5qmW4jfM8wC5kt3uzSbjx0nykwQ1brD'
    b'Wq5+Z/QHzLqxlD0otNKWe7GdHMCTtTAjagLsQF8Q4T54dUMbOL7GhkOEddCd+DZsCctlTIfRMbeU1bkDzK5j682tltS8kz1Z9E4v'
    b'H+v2aMidQo/iWdtu99KOrZ0KG2xUS6P+NV4+oWBtGzjJnPGj2sCbFKRyToA292kNI9fO57iZPOMZgTuLwdMiCA49xZayC/euAE87'
    b'ksR7dcfNtH9rMVq0F6Q4PrlPvx52l+ogG05C1v3aGMWPyVgE2DjlVhFi82IZznVLJYYfxn513QE4HbTr/zKLOPNsOubXi386897c'
    b'heFrpQ00T5yKgvhAP5D2PvuineW+a7jLvlT1ww7qrkPaPaDDo9lnjeKzFeICMS8DZaNAMZTDGWvOnhjj+jLfegV7SNmjTW/yGsxI'
    b'OCtMHW/ULWjJYFs0C8o5QL3l5CWoqSfJnZN0rZcd9SgMz4zaGtZhgum7Nz9RWY2VTy2a5NKYCpL+tGZtJImKluJYYEKmCioEal3u'
    b'KrSs8O+5ziq4SX9xJTcbBZLc6xgwBFKFDAL5Qkj3Rw65xKFVAzHKsCfAdpHbRjhcGXq96Zg28BhHJ3FDgIrjgSUHaM2tSiGPbb0G'
    b'Gu0YShLC20EgLeJ1D6eYqoSLtDPpZ+5vlf4XboHNZWWf7TCj2jAfspOwFyQGOc8XEP2Vlww+Gov0TgI+Bqi23K59DayMjUYHXJ2I'
    b'l1q0n6tPLUD5PHimUhOZT7EJfwuTIwJVlddng1osmhKSKPP8RGZl8Ovisiivi0jLCOpFuhHdgGwIpkOPwkefPnB+p5bUbNLJNaZo'
    b'0N0AZI3BQQeLErRQKJMKHi4J++n1XsrO3HXw2L+MLHV3mhVKb/fBk4Jges1JxO3ITZcwwKg+8/MUDMOMrOQtqRJsl9JwDT+hg+9I'
    b'G6lJPjj0N+APZFxmTCSVmSrNd23rGSX3UoIDInwr0rbDC1rfZCWvu5FVcLx2jqNcmUX6IkVwlx8nRYSRlwQFom0vIkWIPRgcJ9cR'
    b'MfugSq85c5TU4xCxIk81z6PdoTGUdSACOrLzZX5Ua5V7QsBtcuxv2u76Yg0CQQiUmzaAh3FmOrTX7dot2733trchdu18+YQIu3xi'
    b'HnzMNS7L6hoi6pIJH+BV29oBWtytIpzXafa7Xd2IfesStoq79PWOVW02g24MQKQGvcqDo9Y+5XVEY7nXIt+jSxmMxcwK6eDHGCQj'
    b'QwTcXn0HcFUAJaGtC2YnlPAgGYUwFaqfb6LN91Qnn4jB90MkxuC5d8PBsXddjNS0LQs8zj5Si6/Y8TRfNPnhm3hsEC0mFSbQuIYG'
    b'yXsXEEXiwqQmQt86wTp0juhZa3fbxZ42pxCZyL2opSOY8Q50OB067MCmUHRItzd1+Q0YlnXYNw0o/ySJIUh5BoYdg+Pkd+AYle02'
    b'2xZVbto06eLCqz3cbMaKl24R6cloTnC53Wv+KrHKN2ykwNOFGGe9b+MrEJGs0kGkGRRi11TpOkZ5TQiKwQFM83rDX/fqE9dxe2aJ'
    b'O3o0RO4pnczLpizAX1pnYHC5tfainSNrr949yN7N78UzNhDdaiNW4JyWQuaE1oHHiu8x+BiIfSagRzf2mYRIHtrIHERK7zEFEQj7'
    b'zEB3J/aZAO2bWpUN5blVZ3eAUY8X32MS4kDClCh0m3VuqI40EvL9OLbA6fU89o0F0pY7Kl0fdRWK5xYPsm3U0bYRe9X28y+ILJ7w'
    b'qaUa52KQkSoO7iq7zFUcN5vnn5dbUQwxS+6Y4GUN5OumQzsT6yYdZultPTscjVV4jvB3z+uoysPhScxl+tz1to9GDoJFx2Hwbs4d'
    b'fyltxAKFqLQzB+rWIvUc9t3QuKaECwCLEswKg1mnXZlbSMYfsjUHP9pZKNeHDoF0CfGP3g0Wu40K+ATBIThKS8As/aLcrTNEoLEz'
    b'rPkmLdKVgKzfHq4R/xNmk9plzF5XLWF1hP2hNYqZueclQcVRuwnJI0VxUtrKqkvjLHKZjBjFm2lunKrWt47qOjdNDIiRuz4IKpxI'
    b'xoEWLtTH/L0Q15BRCcS6FBAguA7guMjfaQ0x2E/Apz+A1JY2QqI0N6vRGgOhhNdVFuY8gPHmgulsgvQGJOZ6x4S1tA59Qb9Fwt9Y'
    b'Qie60kSSPX2ZHNCBGCBUfQ6RaZplasOFL20dh0lwJlrrtcxggL6q2g6Rtc7uz2dwfn0WmgW/kLkEVtHQ+X4GurfwQdB+tMuKHETR'
    b'aHPU6zAIkPh20lmLhi+QLRT0bOAQbMmpwRD17z9O2yzKU23Tb4s1QV1ChlrauE7ZViUIcJqiXJoUFNBSLpwxxLcscaMejpOBGwYQ'
    b'4XC8slkQNRCC0RwSFlhP410PzRknEY5xIU4PItjm98Xof4uuRU3HWYv0WaOxCdSStFgfjGH1armrVXc27Kb9r/u23yo+/wjdgLly'
    b'bEjacJT1Sa5hStdaxqTzMCCzC5991LXdtxf3Ncl0dCsTiR5sp7V73jnccBR1Y8QU78lGH2gpw8R3zJeE+MWA7rwydapHqnp1zqC2'
    b'vTrH5T+kcwVkUcartT6FJ+g2oO/gbiIq54XiEBmWecl1MlWFot7Z0AIhHMk47qNEcDSjtGBy4X5h3nUUFwPSyfo6va2TbbmFvMQi'
    b'g7BKWZ6uirJu8kWdpBUE8CrqvG5E0fxStYxh5Ew4z968hlhzeUNREH90QpvoyI8YH1F3wY5FIlX0HCuCl8YKZxCMj4LTBgJhK5QJ'
    b'BNA/ciQND5JFuk02YlNWtxDAIoXA7nUDkdTZBBReXpV5luyKc7SCyJJVVV67kRPtPgCCOVFVDo+OtcLF9HXKqnypwjADseBzimtq'
    b'Q8Jxx+EM3uwhBsKar7hEoFUIZI2VhTnozUu2bm11w8GauX5LJAeaVXQn0hnetOBoW26BAQwdV94sn3k80ds97TTh7sh96XNt1L0D'
    b'eZIhI3yQ/F1agfSFc7zLLRvM7k6OsRDrYEKpHJtkcvTkZ+Zy2lnVvWg4nGTclvZx1TZDS5SaOinKUULqVwgmaZBYMh+jHWKwYt6I'
    b'Ck6SUDRveICesxi4i4k2RqWE53zYOGOQywkhV57EzcG51hkKSr0YIA+SX29BD5gsdhu5aLzXPgmLJ5zZNzYQxsHQOMjRL6Jb5h7i'
    b'mVfzTdtNQ+2pll0byHEf7gTPgLykYqzIQGX8TmIa2GjzDUpoPgk6ZfDS6L5Sgpte7VdzbTsMT6AraKuPlZwlf3YhYJ/KjRtaT/Bk'
    b'3Mz1sgbAS3l3eIWpOoTos/Z1JH56gxlY55Cz3RSzwK04tjv6Ud0Pp7x/ROoLTybWUbRylxE8i5PdljcAhPCQKeOBM2/dpqH17Nqw'
    b'nNOmY8b3HEBlLj4oZeBo0GFwhuiek1Rigro6PCfI4SHJN9uqvHKsLC1LdBaJ5UUCQQqld8Y45PWM8XOQRDu1R1YEQ99nfhCYrxA6'
    b'gxt4ZSiczGTHh8eaz0UZJUYWRB59uIWYx2hEMoqE4+OI5MSNjjFTMhy3t4gEiWEsC8ELs6TkdDfr28QyxjW7ZuQBh0DW3tmAKZPr'
    b'ZAMBfTFGNx7Z2GtoHHpu9u/lVlTgxgVs9Dat0vVarIlAiIaYBhhkCSw2um7Xycnz59K7byMgCLnh8fMAERFED4lzJCb17hwwCJND'
    b'Q0A3YDFQ80DTSsCd0OiHT6pDM0rhkF8JxYcAavDL5bV86Sw7fdZu+qaakhWOd2BbWozS9+deiJrvz7zMJfcyr/ZgXuYRUh+arLM5'
    b'MidmG5GRB9o0ORiJnjBiHuia94HiRD22hnqz2G26VMt/ueyOVHUqZZfW0DDtb69vTZPFASHkdnYn2ijzJwpwBx8S73w0k45fBVOS'
    b'y+OIJSDxUva0cF9GQW7KJuCaav/5YA/vJBDtOftPD3PgOKFwD1TVXgl2kERCXFeDjoYZYBNun2RBNmQixt2QPWeQHrAXiwjsmC9p'
    b'dNrxkFk0wAof7FlViun6IqgPYLH7kG2PXYcuYCCrp8eYeRySLEA4gbxYLXdrkokpfuEirZNzod5EYkTOVeJ0piLQTxAR0g8SGIZu'
    b'TbJTqj7cL+LXijtdLfa+XuCIPvyOcf/3DNWpaJtxxHCEPv0BKMxsgcBXl7vdXOJ9vp/7ywfNyf7zYd4DjsDQ/yqvYSehKTQy81G2'
    b'/w2K27aimrDytm6wUrlEwbZY7CiLj0xXIWGTqSMLhb17BAP5aqbz2dClAhIJArb5/PORyT+bAT6lRbLZLnKvm41lpClZSvuTvT5z'
    b'iLAE8u8dRMZCj93f59vhZqMdf80cqGNQgTXlvNhtRJUvsJzTkbfjBDjfqp4NFqWo4Bbo7M8/7XldiSs4kPS4JbkOU2ooLtMbGqFi'
    b'4f1o/zOLaA1WTr6Uy4zz1pZrAR41y4jCc8InJbYKfTSOoXAwo7YQDi2N+WZRKB6I1sBg9DRQfNs10o8rtgLy/ecisoK+9J//j0b7'
    b'w63dD93fayQm1X4EJt7l4jJ59bo/1Rbp4oJn4FMSmED1LVChosnXIhkuqrKuJ+A8i+KaEWeo4FEYAO16JJlBUUyalMVCTC7y1QW1'
    b'0JTAMEEJl7b7NP1RF01n8R7MU7FqLojBrvPmAwh8Pa9FlWOMshDxjrcYoOQe6O0C52dmtDOt0uJyuBHNRZnNBumVqNIVyAfTeiEK'
    b'sA+gaM3JdtHg/0Yw3aBbnyUwqcJQystW9jmgdK+my3y9LtLhwfTJn9cRtNhV8l6kBtd+CskaoZOIv43u3gs+lSSg6I0JjURr3sqb'
    b'9EbOs3OfjwMKVJanCrbRclfiQ+QRsX6MdrAJ1Di+VEVgL3KRvx4xsSMmsI4f7YAJtHVPx0v/UZgRn5zYTfzazx2sYk6jTYztlyID'
    b'MDqxqn23ERs8SL4BbdNzbbhBX9DkfBRNQGxahLxzgm8nD+1W7IDqni9Nn/DaVoreHobB7pqHbB7uZ817WFPsow0wztCe0v9LIbaS'
    b'Mw2GSKfVCWoMLu0FoRm5Y4Atq5otUA8FiPbe+cEo/SLBQ3YKSeiH5jTYQ/ASFbNQlEL2zesi3dYXJZw80dzzVHSABpAwHe1p7zk4'
    b'juGvRhZSosjuMfQaQPvvMvBaBXZzsYA3Pnr3C3RDzvReUfa5C5RfAWuuQ3coTUygKJgVO8UtP4xAFdemFJ0F0d/PbCuZ7AlIu5Ow'
    b'h3m7l0rAjet+4nrcY7CRQYs/WAScVSYEEkxtB8docRvEFGkGiQiCPwLFZFhw8OPYVQH34YGM3shUCVaW3oTSzv4qXVyCJfgEE842'
    b'+flaJD8a1AJNUEWRTcrlhCgApUNDS90APDTTxL3HLolkNDC1gFL8RgQNqvR00eycTKUEjIxvJ5g7DVvdgRgcD9kLED7eNJPFuqzF'
    b'w2shLte3yVpkwIphcvRbQ/yoV0D3YXAcoY+hhXO7rit7kS07qosi26dlK1BMsGmzRBcAr/GOyneKFrN/pJh7jxLzZxLCZNAZD18S'
    b'uM6CoUF2ZRbqipGi+Od7ST8EJs5z4OQiaahCI/jgEEwfMfzSfYZekjFQZPS3PQJMk4bZ6UaYk+QO2Rpp3Tf2bAu1wfrxPVqxNOq9'
    b'2iDd/h5NGMYAvRow84LBOdFvtqzl61pe2XqoefJ2YG/7Xm3bNVrHRpe8/qDN8q2Ag7my+ufQGoQ8d8zqxusQTqBHj1PXdveJ12Kn'
    b'csft55OPnszsg5OYxQGESM7dsn0H+q0coFLLV2mYOs5Mv0wOyPJCFS+XSycXPA0jU62vxRUSNqDiWcadobd4gLJfU2p3MzQ12Zwz'
    b'efP6q3nwvrQAnkZAqxzfEBgWe6eR4HCffmpnMnsuLY+x0JxB1lmmUcGWF50z5OetVVMUSGkbBx2cI9sba74W8mgO+I85KKbFDuzH'
    b'A/fpbEn6lq/TJv2mSjeQqJpu2XTvRp0pFHOTdlZpXovk1a5o8o04Bf3LcABXFUjYkGyrMtstBOiOlO+eNFZk7QxBBc2Oxfm9Veof'
    b'+Amwh7GSJhxULmM3kcthoadbxW6Z0ZesGSmqBn8xLnpvR9PFDmzNs2GoNrU039UZO4qCiXixAk4mb9I1fIAwC06LNP3nolhc6Kju'
    b'+HOTVpdzvDFBatkyzeb69bbKIbMeKq+GkFojwfhBap1AhOgAcRcNQwRggCiaLLD+bXbbtaiHeZGJm1nIB6UCKzKWRFDr83PRXAtR'
    b'UPIpn3d1euGjcTW1VyYW+ihQMSCu6VXbFi9hD6UcqaoQzSs/EaoZa8A2Q1CLR0XeJp+xByfMq40pWNT048YXhAMb0VRAl2Zw51uW'
    b'1QYHxW+HIXwc69mdhVug1hnG2SC9WqkEtHSErwnp2cOMYSipxVvKFzQKgDEv5z4E66sEAjNrfTGwz4pQJoOJxRrkuzXuVo3PsQ7I'
    b'0rFu8PdYZwwH+fZpwAt73z5h2WiP4GusP/FViPUxIJZo62aouNXTQIG7TZ4n7ujdLX/6vM/7d6mp0kyotHvgsjyv84zOIS/CQihN'
    b'35G0nVUgFTBVvic0B46McsvJewzy4hQMS2aR0sRls20gtFhWdzwmmG2DY8tkY7BsqWzr0LQUW85Ke9SkbmjgmhTtmReEScYx6Ip3'
    b'NU5kXL5I2/R6vikZ1Wix17fhMHGdwSSUMmANmYiQzxo4eO5mE1cz6H3BveW99Q9H+B8fdK58q7b29BkrKlbpdggXmGqMjmm5qEik'
    b'xT/GmO4L2RMwnQmmuDw7nhy+HYfTX54dHr8dvfVjKgSKjsBQ40gVxeEwG0bLBpRKDkYhh0ylFxivmwZHTwTCpvptoZ/VQrWEu3az'
    b'DcrgEJQ80OzyCEJEWPrlYSwHHLo+dgo37anqyCUWoPrto+LpMQfggJCd13BY86qoXGx8DqRuga+C2HNWXNARaS+6k2lN850Eu5/o'
    b'a1y8VUoTund7Xp7Rljadss4RFdpvMSTPpA4TQtgauNCyc4kGG6dhgNjqCwiFLtJsN768yOumhLDlFNcIxbxwo3IXNHCbi17z7Nuy'
    b'y5OzdmI0TYtb01eNSomf/DuoU1/ZCB6M3Bupd9fAMRq3W9lIS+le11gPzq1I0bQksCCQwPjIjA/sL80iXWG+LilGY+gUA3ly+Db5'
    b'jIMZPaSGONolUlpqGYyUQgGtVGPiZiHq2m2JP0v58Qq8Wfmml0wS66vTWy2pDQ0sbSLYHLzIJV9F1npkXcAik0cmqh5m2uxzcH3V'
    b'/IautW3L1HeSY+WCE+QUbsXjzrI2Fsf70TGJRkU9yD7z7cuEjMn+xBRL/vYgef1ocpgMjw6Onk4OnkwgoBMcO03dVOk2efYduMuf'
    b'S3maxEmG8Q95Jeqkggzhc1VnvsinoFXaNcJ6STnjZRCmEbjaNxfEuD1IwOhgLSYgSEqenXz76uHri7Taioffpzdff50UO/S+T1Zp'
    b'XiTiZrvOF3mT/OLJz8Bcd5lnolhIQIrhmSa/gojqEz2W4aNNmWCY9XoEozKCeclwjZ8zFHMjQA76WlSQQDDdNeWirMgIvCymwHpO'
    b'lmmTro+BGGxKUPaq2NYlWT08SJqyTJbimn2dxgYGGNNDB6V+A+k1tyI7xmg572nGm8qUoYF1vT/3EJGirCCGQccSOLQftIsLDJ0d'
    b'FhfBPdd6FbvjKnbcRnZ3qN0oYgv/ApSLjfPBdM6Wsal+1rOhOTqjAozHGnjwWuHALXRvZ0cHB45cnCP4578Xs0f2l1qIbPb4SL9k'
    b'knezENsmOcU/4G6X1okxH+JmESKIHs5YTQ08DBoQCtk9Gqh0TEukm9j+cfIObRbtPoym83mRbsR8/v44eWd/e2+E839PlEUFNfQl'
    b'+nYmOVNcbFRyRcUkW4EOwAlvFLTNMc0PYSPMuqn6mYe+na6qcrc9v/Xl9gboYlfkP+2EwfsExEvYbYNAG29NARJMgfnJSBonxZGR'
    b'4zHUlKwCJlu1SDgYotyjn2NUFqWxe2hrplQxiF7CUK5FJYwIhrzt0QAy+ZGPmsWuuhLTRX31YwL6SvRb2rDVFoNBn22wD9vVokqu'
    b'cnENPqLNhaiFqRr7JdoLw/sN3v8vxC0YhrGXywM+NtCkCxTAkytRwa0ICXJSN2KbLFKItgPXpUYqWCkuDZYhuvcgeQhBGyesJkU1'
    b'WJ1AeB0IUVOJCeuWsS15/BERZk5gvihRvKDR0MUWvTWkwsV7YxzRxjeP6Qh+C1Y1yKNbyX5PQgYMygKTD6PBEEWfdCj8DahBjb4/'
    b'RAre/klvLXufoqQ/71PSMsv4JK6Rtr85muVwRV83bJTz1bfOR0cza3wNqFbNr64tr/GtxWg3WsqQZcbLsEgiWkALaqNFbBmsUcxU'
    b'I4Rfs5w/8hHk7cangIIg9lXXNG7CGNnB2BEOi4MuVOo7e2CYJMFxJzS+SDWfqs5cAJUwdMdnZi3lHOBzgN2HJzxbUUF4WRmBvZZS'
    b'B30cZ0tW4Y6T0xfffvfidP7q9NevT+e/OX31+ruXLwIaSyRAZmhW7LanGh87pOetHMwduUmagTQTkrtI8wrTJ4EuGIg3YnNAEWwO'
    b'1ftIQ/deh6bCL+VNx8x706b/hRNODchkQaXDq/oaWlp4VsZ84P9hp2WihhAV9MHSz5tPlq/gUjcDH4xNWt3O6cVQgfSrrMtV2ER0'
    b'cIbtTX5X7qoiXb9NwnlXl4N31AiKNT4tuLOfjt7zSGkM2S+j9a/zApUlMwuQfAuAYjUx+qNfVb1urYsWmCSRdKobXz4dvfcBxHl9'
    b'niub0YcZXnqzyZs4WaY5aFuGhbx4jo6Tdwac9wNtUwN3V2kJ80rUkORB7oOZtfcdjQ2r89U9dcZ/x4nJ7M0U3Rp98sknmVgm57t8'
    b'nc2BSazh9FqUm40oMmK6QKpJkc2Sf0pOi1VeiGdwdV+Nk6VIwUK0PrYuCyMI9GG+oBlaLCG1V1POF8uVlpQifgP+iwZTBNeGELXM'
    b'wHSW28CI5saLOdMat/z5rsjWyvTFfDcHW2lKmEUVYL0GxE4/OT9OIDgF8I00DYk9DRhZcjqVpkeLtDkvQeeKRriFKBoipnW5vhJz'
    b'GSJxLosNnVrpVZqv4WCWioIAPJIeqpIDGd2VQD1Lm19BhWfrtK7zZY6pN6JQ/NI8DvnhVVpc9gNBJd3qYlWJui77QZCFGYh0XfQm'
    b'x95Z9iX47B9OXr14m+jVk9WTXaEA/FL6hMOywiGTrPNCpNUELzS8zrzsU4eALPmePXsXG9CnGDLgU4z8+SmxE5AWcS2yTw1awpsa'
    b'AzsxKps+g3CaOkevZE0yOwLC1zJHqHqv5wegZ9NKwE1yyF9n76jKsdcAJ1rI+ljOBQpFYiVkZwO5NVuA2UVioHA4phleiD+R9/nR'
    b'FKR8DeSmETdD8IinYAu0x4mmZc0dhzYFxYRaKhmJQEEdtVszPg+TEiY0fCKci0W6Aw1E6SilgatQuAyUR138lpSdx6SPFm9JOyqM'
    b'K7RWSylusGYJOJHsLIgYMz2VltOrWVX9/0z/z1lxqcV661UuwHRtnf8elGn4drkrsnQjChCWS8t3TQXAevGTCB+owOpXGD5XQobt'
    b'z5bz9YzoLzqMVPmiIbcNKTeYp+t8VUAnDHliut1CfXDHhi/zSgA367jEpFlmjWC5Tlc1GUfyxYWlGW9yUU0OUinHfzw5Ajk+YdPm'
    b'soGcDIt1zjF9D8XhUTL828M3IwjGcigOH8Ovg4M3ElpdJpCVdbJIt3UyfPGbr0+SP/zt4+mjN+Pk5OSH58kf/vbR9Odvxsm3L19+'
    b'+/DkN9++TP7wt4fTJ5OjN+Pk+9ffvHn4D98rWJVoQGrfXIi8ShrIUAES0mnyA4S6KXc19QY7WK7X6Rb89g4PjfbzoimVCEkkDVpo'
    b'ZKJuqvIWT9pyNechPkTY8xpwhXcJrk+S5culAIeNnAT3Ht7QBTaFiMy/F2pnIm9k8Q+fJ2cDagz2OUzpDOaPdxXcrODwiqCJ4jZY'
    b'Yy+LsyQccWaZLhoQSHNJKIKeSMEaQNco52p7eXt0CruwsJYpWiNVr2HE1fwQcv8Nqvkj/vuU/x4e8X+OHssS9Ikvd1xR/npk/XJK'
    b'Hlk/GaCqSYXV3Bt7ktfA3BBy3HndnOE/rQTEL439VqWSf6JvNP7Q66fGa7aqpp7OFyWET+NMTVhaDkGp4g1BMCivoZTMds2SXNAt'
    b'aXBfAc09MpIt+P1329DWSJ2U1q8amaPtjWEOgIZMQP8ogWW+ED5tDjbXCUW1Ps+uvJBM1JMMCEc1B6na0UEWZQhkqz4Yoz89YUEH'
    b'EZDsrV3P7DS4DZqmW0VaADvAXzkuir388B5YEJh/P1WWleNLt0FxScxGv5wlh/PDg4P5wQEFUQl3NvnKrGUoGeQYnxAIRkYXE6Cz'
    b'1gJSvT7rH6koR6kq9PH5iHBJ4ANVJxy/BOTUECx6IR6u8592eQaKkWW+biBmnmSNeHyZqLTrJTNQ+TpvbmM0Vu+M+gKYTikY2GzX'
    b'AmkOj5UuYFI1BYzDyOKFbufpej1Obs/zAv6HZi2X0uUySOHPBpA+XNowY337W072/hIkcYDkl8mtyV9cQr3AgZvdCLlzRjplF2Vb'
    b'f6PVaFHZX6dT0fL6euvYcDtjUB/+nQ1mj5UyNMh83LBYNs0LkjYbiA7hMUiEIV4ul5DqG82FZrANqYbMpDUnwyIDFnEl0EvVa6Z2'
    b'zv0IQqTq1rXE7t9Fyn+pu2cWpjmoRJrdssKHF5WweTB2q1k4y7RLdh2CdT45OGjdsPZNPLx7ER6GM6dtDIYU9SZdr/17NjUNSsnZ'
    b'O6sr73XPUfRnOfPrMbETv3/nNimY5LsoDAWcUGXFcnrkvgy+Ue2FUH15N1mX1y7Dp4rHa2/SRVWSXSZFVlBMW7/a1SUopcBMNd27'
    b'Nire5uykvlezZdpAZuub272qZbdFuskX87VIM1HVF/l2r+oQYJK9S+de6MY+ABZVXkN6D4GLtMybPpXAPKIRKyDKO7Gt8qLZG0NQ'
    b't5jlG1FANFDAtRyPbIx92zp0uDKiZ795b9zkRb7Zbej+GO4EZskBI/t0BQJFZo2ko11ZzWWiYKP2IC3S9S0KtagirTCHNyBppfyy'
    b'SWuIiWi385WKMMWcCX4WdZNv0kaX0zwX2gaQoSfGgQBKWm7nBSR/OBonj7lViIAFn83GpxBpaqQYDYBkyAaDfIpVPyqwuMOMIwxl'
    b'Kc4KOddchlrCFc/mZVmjaBu1Xs1Frek61AXC/jAZGGWpxek2rX7aCc7BDeGwbGhTtKywslZYGsZ4N+GkmDP0oQPVsNJ3tB59ILsT'
    b'oEql9bxc+hI4g3nvLYljFcmuRh/HNJlpPSPYhYEwZyWatGkqcnAdUFl0j35M+oAaDcfC2o7BGE2uzNB9VmOoVWBgDIHFeXMweIYj'
    b'oSYdgyuAsHwpDJgh1SE3ICHON2mzuAC9nlhQjOHFrimXy6EGYx7y9lIF9X6G2oPaSmRbCYFOslJQx7BtNKaBHZ7ILiSwTiFd36AS'
    b'y7wB22+w1IR64gbgYu3troJwUYo7WAK2TG0gtuoyutThKbR1BsYwoTi1KGqIvCvHTRiBUlVbIWBoe+D5LS83UA2S/y3StahM+qB7'
    b'dDagr4DHMSwwb9KwBdfABAnyhKjyDCmyALUbmVYC2KHshNlWO0TyGlmXq0qsFMBtVZ6ndwZrc/B36fI4uRS3M8nDY81B3/buPCC7'
    b'UQLQ0uoiRTseyywvVm7bWQoCRXuF6MphExPCFtKEOrp/CAjSoiMLngBcL60a8CNG9m/wNnB0mA+XS2a+ei8QqNGoMdUqV7DbHNqt'
    b'RmLNt827hMvLrJbVhtR+Uu2ztr2mcLGue03hAm0Mfc1ryxwu1nV0DrHZPeaQcFJCtTaKnsez43Fy+PYeZnO711ziKa13JoczSotL'
    b'DAkkLdakvpuCCCtcwp3UB4XTArhWW2/dhsBpcRnHYGy15/Srza7A3jcCW+QkyAkDZ0u0hHJuyFuMzRr4erJIHFR5OB0n9mEVCC9D'
    b'p45ZcBsqJvegLCh/R4pqiPQrGCq1gFhRxgw5wWvsn4vlCsQ5rmW/MS+KfUVVnylEkB9EUYvN+ZpLDF2uGK8MkA5gXi5JhmFzxLZ7'
    b'LbAwwZbZEoRsUXk/WMYuQf6nbSCBFeak6xDXCzBV8tBmO3Br9EYu61H84rKCP4HF+WmXggRWgu8P37Avt9qgSZFgO1qX3ppWpMn7'
    b'6oMDPBbF0I5Edl+NSwtlSSxj8Zqk4AdiqrctMBdrXV52mArinxef2iJKyDjHdo/BSQfxFpg5GgP1aabHVFZefpXXp88ScUUOZgkI'
    b'A9Yp5J2rVkJ7zB0djJL/+h/+OXl+8ub09RuyChJFlS8uQBSAGncD4uGjb5JhLRbzw0fL+U+7tGoEBC+sBF4pprebNWS6+aasNslj'
    b'KgjReB7PszTXxQx4WIOzsmCEXHl/TNJKQNR86AN8oF6DMUhSlJNySweiIRR/YHpuUHIuwy7t96IqJyAXR+12sb7VIcu8Axp6LSeL'
    b'L7vwSk6k/BaI15TWgKrVDJlWwk3I8MgWrOwKm9ZAwPzNAVIdmixWt3NY4xnsU/s6b3UnVm8wTh4dBLch1ID1278dv9ZgnBz6rXhW'
    b'wugipOc1EpHfLBHNxMsFlAPLgjLVRurjjQEcppSplAcQ84cgLwU3Xhui1RiCgowHSrHHjfgw86UNNsyiBcV2qDpVBmwWlIBBcxAC'
    b'bhbcfdz/cVIWM51z+KK8ng3WYtkM9jCRXg7OarGYSHx4qwgKULQcXD1Rc2G0OnqfgEZjHDemhgrmFI/eKw8uHAO4azWlMbKYfXLU'
    b'HxFR2DRQlmOMDkd5rr6TlcEqOUotRLN0qQW8UhbKklrsQxyC28doKLJ9zBJ32T6B+v+Gt48xG/e0fUSz7Nw+Rqt/DtsHuhPbPuHh'
    b'GNuHK5vbx72eYZinO1zPrEsLPHmxWO8yNJ4T63XeiEB0blnGMm1T5THu4952kKMWJm9ZLnY1D06SgZDyKlxbStbB7A9NLFVX9wIm'
    b'72teMvg2nV5rj5SQYp2vcjYqsYGM0eZc3DQzJXxWHgVU2UAJArPmIDgyBI6hFbGaAysJVoWZF0cHyJekP5OmWGDPgg7GbkjODr0+'
    b'PC2WOUo9cJFCtNmi3K0uOA7QBC9lyxxit6LvNxnv1ItKCBD6uxYA8CwHchSzd/Z43gPb/9Mur0Q2excZmeO60292SPnYR1fCvgZy'
    b'MmhNMFX1UlyrRO3esJuLFBzjftqJGpyvsb29x4619MCp09Hx+ngbjyjVew+AMgO2sRI6uV8Gb+1EiMu8qhsrDSJdToPd1ATasfd3'
    b'UR94cpl2V0M+I4tquv62uwJYLYMeUupA41rZsI5QqWbHiRny1lAYogOXaoskdKQRAtuovJHKI2nqEtYS/RY9bwtX46Qr0YtY5U59'
    b'VVv1W9W2bM4wVWPLRyoIJl7BsmAKZpaUCQi0kZQqbrCYEkDUTqzFxKvdKErPGwNvsYzCX6QEeQXqqWG63l6kaP5Fii78Pca1xB0F'
    b'jANn+6zSIis3JLOgGvxCyHhvoNMAgxRe4LGcbcdAIaQYDGpDpEoUeKJiO+XwFnplyHTiSNO6xRqm/3m5AuZwweqdvCyGz7DDrF1b'
    b'jMFaYw4RnmeHRwcHfYbG0J3h6Z70UFZC9W59hR1VIw7N93FpVWNKFUYfJaRh4w0z7+A3maukN8NHMHPy1GKDvxQMFuvk4cPkiXEE'
    b'/VY2E9z3Dvz2/Ut72AFnm0478AJWnwEjDCOInLm3jf1t7hrrmKItBDOiDYeMzQR2QAfTnz8BC6RDN7dBYJ853EwcMUMMq+4rY6o5'
    b'GbAfzd/7qsIN4HHFD+6J1vWxJ6B9sZDYesulB66ttSXBzIvGW8EwCbGmgigJXr+BJ/EKmKZaiPtwRjaAL0cc3zwA0+HC+GOUSHkc'
    b'1DMHqyT9IpT6AjDq6ElIGGhRN+9zP6SyEcvufxi5vAkI3/paKI/RQjulRMhNCkE8breowrooy1oox+S5+kaRHQIeyhQe+NkPv1aW'
    b'aG1WCJ6MaHFeBS0JAtKDugY7PLSLnQ1eff/6NKDlg+UiLgxXhC0E5vq1XyUT2+ZClcZffiHw+8KMNBhlQBa23sYRBGKEteIHPFei'
    b'Oi9rYboAmo9aiJn6XxuOLc6rFhail3HFedVCntp10n0MKtoPaLdGTxaGfGH2w79F2AyjCwGflyt40w8HF+v63yIOLrr5vA77lPNF'
    b'T9uU/RFyuyc6OvwiEDqaT9Ms5S4IWAXsULqw7x9Fk0PRH9K8us5rMwaVmhEM7YwBPmbLwYuvn3173JTb2TvTwhp6P8eCIDm4HI2T'
    b'JyMz8l8bWYWq/wZxuroMEtZxgqEF53k241D0/BPD9TBT5uUXat8H2lAIWr0vYuzZGrajvm9LtJcdUUBI7YS17Gc71MNuqKfNUA97'
    b'oVZbIcNOyLIRsm7nfyTboI9gF9TPJugj2gP96WyB/tR2QH90GyAyw/mT2P788e1+9tKvBciWpVfr0qndtz4tMIS99Gj3pkP7YP3Z'
    b'H0N39mF6szvpzO7oB3vPurJ705N1z4SrH4vG4PoYerEP0onF8PBuurCPpAf70+jAPrr+y9d9YYDBZbpeo7d8GCK57pAvIiFZNOgg'
    b'fsUe0/ezuqnGyQ9pc8GRZaxh2JEJqQA1E/pCEd+Ok5ccv+8MonArrhuWnHLA7xXhkD0slTaOfjsu+Fahu8fMkNPshhYj8BxSiexL'
    b'sQ3p4NYShc7umWdade99W0MRuy+yl1ZX+gSv66jQEWymuQeAHyN8XM+JxMOmKJOrdJ1n8hiNTqdCTDm4zsmOBYT7+NjMPZbjXecL'
    b'ZEMVRiuUNs1r29HYGa00+PNmpTM/Af4fOL5tS4DHvLCplN8f+VktjlteTbdfus/O6KoR2RqtXWNY3Z2JYU5g2WxgYctOt0Fj8WKf'
    b'eq8ePGhOOL8Ut67NqIKHdydnlNLiM4h4JEWMD9BKQajbd6xvb5oqDdmyhmFSj9qoOveKi+hmbRtV4BlVy75xaitVYfNSr1JgGY1Z'
    b'/9xo8C3auM6zHWQSgpJDXRA8fMV2NlindTMIqPvgKYuZUSFYRJu4+t+ZuLiDvMfYlRboPvErHblnJDilWyoYnVJfcTXtIn6zJzeg'
    b'KtDluw/l9casmGlPIR4qxg21ESxb/NnanpSYfkCHuqwmgvjTedG2sUJfTlxAnRfuTjwzUdO/jasj2bmWm1gT7lP35avvGG2E+tg3'
    b'Jru1j3RrwnAWcPeIh7IIXr11eAtYGLh94+Iou3fFIzEJclmo1sDE8YjYeHbSDzvFFL3zruJ8KbSmki+G8/NG5qqHEGDDc1r5eXn+'
    b'u2Mn2vxnn+ExgJcvffM7KW7f0kxtIJg6HDEIjRoury3JdksWWJbJblikGi0XkLJ2pKc9ljkjZUT3tsI6PaSVVsZOlkpya4bnfnTk'
    b'zrFEqU6vIqWC3VFBsjBfowPISXIZzH8UqhdNk2mmJTLSRDrVzU/hTmNWQrcavw3XKCGDqTdT8nWwDlgUZZlbhd8Ga+TeUHJzBFbI'
    b'0GABI8aoNdlOpkxvup3vwc4BrsLWBYGxzA4ewmevTBSamTIoAMjKKIShyFwAZsq0AADzsw+gbZMGt5S/PQ0vUSBSFuvvlz4cWe1j'
    b'apD5AkwHzrf1fCuqeQ2J1J2BxIpFdmMgxbCLs6Ey4S3mJyl1d5pfIrwVAhMbVo35uZaPMdu0Rxn467hHHmZYGzX3pJGqyuvpbovB'
    b'IukgMc+mqrz+BJ7Xz09Pf3M6f3byw/yHl8+/e/aP82++O33+9evjpNlt14LOnOl0qsOVDljBtNlCDnVYKuJ00OnRSo7l2GzuWQ5k'
    b'+X2KpTdOMZGCm3q9KHdNS5uBUn6LoUKt7a2q8rqRydJ6FoNm6XLTXTS9wRRloYKLtMhyWG0T7EUKZv+h6YNcVLcyvRiE0Q6Wyqp8'
    b'2XSWwqDtfiGzd7HmzDKxxswykaZ4cQjChUizqiw38+1Czb6VTW2T3sTezy/y1cV8URZXOVomyXJGcj65JEbz5lfFV0S+byD1EOaZ'
    b'MwpgPGkOIKoVWIPxJzJj0WJdFgIE7ZQ8jPZ1W64iLnHssI7ITZollSgfKEhAnA9JJtXbtEZ9uqI3pIAoKwg1NgbJ607AFZjbnuaN'
    b'2Fgxi/IlqMvwPCl3DUYoc2yhaz5u5GeGatGucie56ZUowF5LqOtjumW+VW+H+CThXKwh8rA9R2+75gTICfDZy1yss2P/iMT3I8pc'
    b'Av+FOYkRWnNOHACcphaXX45mCIiBxwVmllhUOefDxTeffaaW/aS4jd4c+HSQ5hEwHMObSx8bDMz6djbw5xr6RGnA043oKmz0GusY'
    b'v3VV45Ayfmu/KT0f9j0RhgI5jyDxFyTRcO2gntFrSsa92pE8HXr4EJJyUA+nRiXj1I41mYklhL5F6iMze5ZFU5Vmpk4s+Xf56iLB'
    b'aCVEb8bJurzGJOFllWJUUepLjR9EBalG6jHHyl9diCoB2jEB2pEARUkWAvNUmh3GnnYe0LOD6ZMnjsdJx1k9A5+CHlX0ITo7mLpe'
    b'Bh0n+Oxg+shpo/0wn4HrTGcFu0tH3eXNDh1+ES8fOO0DPTIT2B95CewV+jD2JSbQ5GD66DHsYph8B2hdJhDiOrmmeDp57YPKa/B/'
    b'qDnejtFzyiLsAIRkxHUDcXOWeSXGlJBYJhbWaJ5c50UNfSpKE6QtO3mQYHbbdVqBvLcRFXQhbZJtVWa7hcjMmrNHyQ8nr958d/Ic'
    b'bFuBItXTflOuOacAdnYyUbOD6dNW/HR5FsCen7dVcBkYQAYH3VoZpw50C/Xncbx4oDcHLdADfXH67vJKPYq47FRgncKcFXTWSU0f'
    b'Y7ICy2JvuSfRLRflyxxosC60DQ8PpsmbC5EcfvGz5DrFpOGQpgNykqL4uMrPd01ZgUgSPpXntaiuRObAO/riZ9j2NDk8+BnnnaoT'
    b'eX7ALmkEzldyvmsg9FV5XScbjHNF11AHXlMm12V1CXwGpNukUPCQiTMvszoZYhrzRZU34GSSPPjFcTL44l/+03/8b//lPyb/+j//'
    b'5//2//xv2BkH5uEXP/uX/+Gfk3/5v/7Tv/yX//tf/5f/Nfn//sf//V//p/9zMLI3Z3QKA5QwzOXOTJzvceCy3avCAfeY/ff0PdEn'
    b'YJKVm7xIi2ZMWRFTSs0AByoEr5+cp5BCm0/fu52mfQ46u8qjVsoQPLq+2Pc0dbvVfZo++bin6dHRh56m3ST6F/uS6Kf7keijx39Z'
    b'JPrp3iT60Rf99u3jvfYtr29s2wJ3LCqe/QnNPjDHZb0DjjlvLoBxWQsKtY7TAhqWXcO7u7nbzu3F1NpVHu/NB7dzAaGN8rQFDcLk'
    b'ZF8+uMdOtxjzp3vv3FZyFdgpJj75FQJ7xd2JXTu3bQyhndtSvAer17Fzv+jcuUcHe+/cxz137sFeO9fJpJWvvXv19/45Cq5wGeTE'
    b'5BsNezXUkKS4EkklNsj0pEndYLqy34vqbht4/6P3yRcffwP//Gjfo/eLPTfwoz038MHeG/jxvhu4lTAGtozbp64N/Pjoo27glhkN'
    b'sAEHH2MDuxzbvW5gGtB5Wp2LtSedeiXgZk6bE1IaVXm6XlPgybVoeGmS7XpXy8MXlAvJBnKQl0u87eTFFfk4oIjqfJetRHOnPX14'
    b'hz29Nzvdjt7BPd2CT2HatO+e7m7A6lDbfuh3KH882Uq7gPE+qIc7u53U42A/6vHFftRjL8bd7XtUgRWYyT8qpfnFXoTGHPT5zicy'
    b'v9qt1xPK65cUQmRrMVnmqGBnmeUvLc4eRJLiZouOvpokYdxyFHsSS0HS/GpT343W7H8BcO9HH+Pq7oom7/8C8Phj0xoXKT8erXn8'
    b'8a8a/1ZozcFfDK2xmJp6txXV4nYBJrDO1QQYlHRF0bQgoVt+JSqMiZPJm8kmv0kwdywwMikkbUPvol2TKAPlO5GWXrvekS38/M/w'
    b'atJDKddK7TpJy946tt5yxD8BaflzuwT9Yi/S0ka0AxKVo/6k5WkPNuboY5GW/VQM5qCvRHUb5GVcwkIYNGkuqh2kWwywMzm4e0Ju'
    b'E9DqLFKInQ5KGjSb+GPdk9yD6aPwLvsq8Z98ZOGly0H/WfEue9+Tnu5LYPbUQbs96iAwbRYYIQKzl5jUFdn+d0JgFmWxgKlMG3AQ'
    b'oYzhLn15LtBeAmw8uERS7cDeI18L9Pxz9SCs1LwbJenDRdhV3On+KKzK3uZATz6uFLVN+XdPCsx2vUlof++pwGyjtvcgRX28191k'
    b'Dwbi5385+xuNIFa7tMpExnjhbu9v6e4B2hSySrjOM9/EzzAFkeHOgGgkmoDkZXGnHf/4j8E79GJQPkzu8dFNFvbf8Uf77vjDfaUR'
    b'e57oj/Y0WXiy347f68rQZY9wN5MFFzXvxarsaatV2TGYgz0ls7CDL3obRbnsdEzDc7QXwdH3kAi5oa4f/jy5epQ8P3wkTeIeT45+'
    b'MTqGyOD5ZrdhRPqcuAokTWDEDrcfqb51vWQHz1BhlBf5Jl0butxf2rD+8IsnP1P6oWnyBuemTupdDbZvInOholU0Xqs24GhXJ8Nf'
    b'nU4WEM14hOnLiO0hg63kZNeUk1qsxQKUTygZLs9/B2TzSriACYvqZJlelWBfAm6UybOTb19hVquQDd7dRD/7S5V7WWRbpKyX6tvm'
    b'p/Y1K2mTY/Yh+J03s7210v3vWB+swfr4nNtf8s3syR6cWw+p8pP9ObfelsT9Sf74vo1bfb7xLTsvqbSRFi8nowMM5Wc7cJvj04Oe'
    b'quzVA45EXAckTRihtKzUO04kWVYYcOGdG8FnrOIQjSWRHLyf5nW9O69Fo3ojA5qYkbzIOceJp4tu0hCpEIIlMLxjz28bi8Lq9iwK'
    b'UC8u8jZI4c/kEpslMz0fRiSmrE8MqUChSBSW7EzOoB9DxfjWI3AKdDg7y3pEcirE8NnJ67+b//Dq5W//cf7mu2d/f/pqRNGDinRI'
    b'qzgLROyWqJN5ccv+cpYVHMbR1Rpma4qBys9vh+5YR3rmp+nKiDDidHIG7Rln/sVFPlunm/MsTW6kb3ixndaQElsM7dW9aV/TEYdl'
    b'JeCWU6MZtCM4x9SwGurZwC3ydroRaaGgt6xBH1AQx8+NRUBr4NWG17HG26sYjbxHd3Sgi77LoGLmhlV57Xq0YvwUO3YKEklsk9DZ'
    b'CuABEXXSJXpJpw0AlCEDzCAfI4qlgLXtSB2R6k44j5EKEYAgjGgdkfpmPA+nMucELrbTvF7mRY7+/Kq0QYidVqxBT9xhAFQDov2V'
    b'o2xYIGgmMX5IbAopuIg5dxw8JFaBQ4uYNSh2SDKD83QYqsTBRbiOUVMG5YC66U2wbjB2hw9JRubogGQG7wgDacptV2+cnReGc3GR'
    b'd8CBDeXXtTmLrSjSdXPLkIDZUZ2cgIfh0Sj5PAG2N/nMLgHNQ4nDI4tkUTcU+ul8VC07eM5ISsOFhFUG1ipQn/cERhhnAIOLV/IZ'
    b'o+n+4AgfbXiPAB59UAAnPQEqj2ANMT2vh4TCo73BKdTV4OSrvWHZqKEBBlFmf+iwNbIqXZkj5y3DZx/HNSg32xTCiXnAZOj4uk+A'
    b'ZA4OGApyrAMBGIGOv4M8L+dr4Xr+94l5HAkKUKXXRtABiHKd181Qv+F8Y6qAl0igdzADjL2giKXVpsyF40ft8YHalSE5qCiG9igg'
    b'okxyyOMrr+vjYLgECMdJMTPVms3Pb7kZ87j+FX9+JerduoF6nDwBhEx5djNWjstFIpClAkGX3aWzY7vfb8cgdKqa2aFxEgJFpSNw'
    b'yD79dN6EIxeMk+VAR095l2c37wdGJhuOgmAEfKDKZ/jrbf8wD6oQ1aeh89S6XI2foMTvPCd1gfXOsxs390ZksMc4OZ1lzSgNxz0m'
    b'0iw/TgYDNxWIikzh8u7BHFIS7THAeDz0CaG2F6UCHowCDctJkR649wDFLncO0U1Ulgpl7mWUH0viYlc0wmSEYvqZ9XWUS1DfzAYs'
    b'JRioUvTam1QTCZ0mO2QH581UlnBgBHboGSAEINx54zZ3NuAeQnzVXY3X2UF5OYiWw8sPFQsUajkxKPZ0O+evIiXGM0UlaQ3vjnsN'
    b'hMI+9hnMckAxIMXNwg4AKW4W7+8w0Amw3sXSJAD1FOyBigwGavH9SHfdW7l5MA3NQD3WB6iqPp4NePDI5lC4lu30+kJUAqLteDNk'
    b'SRrET0NYd+At1YFADZY7Nyap1Uzw5DEmw4pSSvmkZZBSEF0YMYRJ7jRzh2HcpHEUETLJw02rtFiJ4SEdduWuAZZXj2cKh2Z9Ngjs'
    b'EoQQeC+XCqNpBoLl7QodChaz+BDHk9dIKDHuKuYawvpqtNHzm4FQjNnFRbrZEsXVAVyNY7CERHwwK73XNxSfHJCwvHTFQ7gm3D5Q'
    b'PWjp0sKE1oX3s4RM83W5ODt4izI3CEs0CrdFh4IVZNdoQXNlNG9mFx1qyssBnOomvYFdjqytmnqjQW/+9SIqABR+8cil2VR+VeWZ'
    b'yut0roMgG6wvDwCEJFTODxtudcn7yseU/8GSYqc3M2fkdoVg9zcp3GPPdygClzNQZDmQXJFpxc52aAzRhrRJi10KGeoNgDqMeDtQ'
    b'b0SRNbLbCAPT2b0ysUx3a5iS7lrDQHh1leOFYjGC2BAADfrMJ2bMYSwCTjWw1owdrd1iQEaer/7o0ooy8GDSSkgXqJZMYs4m3Yar'
    b'eIs8896EK+6Fov60BmmwjRtAiHUv7BWwiLEHGC9ngQM33BVMe4ZhOZNZUom6XF+J+RKqyeYpZmds+06BCgbnyM3NwuWdCK4k6m4J'
    b'D28+s9kHQjXyvZiPd4wYi5TXeVE3AFU2NnY0XGDoFMohIvvGrEB4oaIozdt9NogEoAgsIy8YUeax9W4jmtRYYKvknEwRgqnbNXr4'
    b'Pdxzw91ps4GWUrZD0WlnlrzA2TQ+8fEBhDI/2pNpcFb2MQrHIjJWxu9+NeGAMWvC71jN9vPAALJxAj8ZMHodLQDKW4OOXsnq1olg'
    b'dcr6EoNm4iaiF2VsU9jWp57B6CID5n/jpJj9geE+0V0xNg8LkkEQxLeIlqQEVI6akb1T7dpxjbGkDLYPWUSK+e+ATasX6Tqthsib'
    b'6uiYJwWztDZhwlLjBNR8EON6JarxyNd4w8YxopNGQSBfmRerEAwU/wU0PMSLEnTWxpiv4g1iqf7tELh4A5gHxR8VrAAQREhcgYGi'
    b'QQpXmePzZDpGPjBqws+lY/Q1esN3BEVpzZkPqCpC1mGtX51++933p/PnJ786fT5/9vL5r79/EY5sTagL8RQhVamoGt5E42RAL62t'
    b'pSkj/ZbC7JbjHl8ZAmjzxHs7locTStpANKHOKMTSuqlo2KAXQ0h8vjoogJ/c0zTGvrTo/EHcxz3SIX5BQmpIOINTa14bsTyn0cnC'
    b'eXAgYF5e7PRigyAMLR6gsjJeGHlGD5yyalqJ7TpdiOFAh2TXlQCYf5OFt6G7rDF0LMK3UTuhhzkvtOR97kRwNs2zZWz1HZOeYCxi'
    b'YG45faZh2sOvYpYbJGAtd40pXPZl94YMfj7GuMB5oUDnDbB811YUZ8ndwnQoJaS7QQZ4xxoMRl5+MV4ILNmBDxiMJK74REvMZZUu'
    b'AqpPHBLFLIkDYHu7FhBkaBqHQDZyLQBYj6zMRhbrfBseDNx1PEDj5BDsRjRZhfRPKDyoBOg1aYSfUz/NKaaCX86SQzH5omOaQTyE'
    b'yxFQO2AyIWnBga0+JNiuvoG6oopyzyKFsbuqLE1ypCjMy+AY59H5wiwGoRwpKdRsWt9MdHQ1H5RHgbB3cExY6ZofmZkdgiYJVIDX'
    b'zW3CZoi0CEyOPgQxVkebhvjTZCSJCeOXZVriTYSdL6bdviMCw8kG02694cN4Hw7yvpeUSPPdBrl1aB61+Bn9caQ46gSG2Ps9CDMo'
    b'J0mYhUypId4yWOV9SDAAJCTE/27T23WZ4sHLTflR9S16LKv3ob7SGNRgIYw2qaOju5FoDUaT6n2ptAuDKcx+hNoFQpTnjrTaGxXQ'
    b'pr+S67uTa3dCw2R7OXjnbNP383dY5r3C8MG8k7YHW7QLjWljYKv0v75ngQv3/s4EF/I9ng0+Pt/1jPCm9QPOCm8q9zsz+GZy+tsf'
    b'nr98dfLm5at/nH/765NXX786+e756zAdJjN6zf3o+9dx8k5yiZscTCHQy0NGiJCvDuCVUgRhoYP31EkZ9rYS6KARAnj02AN4eNQX'
    b'IF1Xg2D9fh4+DYIF29uvT785ffH6u9+czr8/efHrk+f2Be/Ny78/jVydqVPoGFEulyqvzm3dCDRyoN/XaTUv8zUkX1MJieomXS3X'
    b'aLmgE+VU1e18V1znBchn5S2LtH024qN3bZXma9Z+aFmXcfLXTcXHvXQPU2ZJce4Az30aabRQ9JrmnKdOs96ZKm+WbrF3AzU+VPbm'
    b'iIuoKSWUV1xRNrdUDkDkjBc2F4A/FW7TvBiJxLi605kwnQy2jw2Ev2BjOKZklrRuUWzP7BZC7a7S0q6/LtiT2GogK+fMwqhjTRCG'
    b'5NZmYRCfxBmmPsxSjFHqxyRFGKRezFEXY9SfKSqrfJUXeIV9J++W8GdsXiDxP5J4DY6p62OLt+AJf4CVH1KNhzRE0KiKn3Z5czvh'
    b'SMRwq6actMkzGEleg3sZJP9J64Qk0Q+SWmxTdK1X5lqTtbgSa7ZKojw8JO5hRaUqiPQpB5tO0kE8wHyz1TT5VtEoiI9aiSWsfbkl'
    b'F34wcsRuJvU2XcDvuhFpBjHI6osqx8S+DI7LSd/V89tkeJhMcCI4HYOFG3IC2aABOmHJO+A4YL7Exw2ebK+uPkmsqtJOPi+GyPP5'
    b'FQ0DCcQD6RKh0h5RTmvAL1+agdnX3ZJfASBcj+A3S+ABcn+YF6jx0C/v3kI+g3zL6dqQP+PUeK95F8sE2nbObWOLQ7MTCXwiMRk3'
    b'FhYnez6gGIYDkCdzMb1qgnIWK6WlL1sxP/MmYuCAQdIBB/5lugYWNsXtEIzVuYdnl2+Tidq+Z5dvRzzVlP9Np31ju/acTu1cZHpe'
    b'JJmw0osZdvDI+Rk3AGnC231DGBgKbkgu7QKSsmj3w1QUWQ1mpcOBZihA7O6qGbAHyoZKa9iWg3cuzPcWJJM/VRdrY61DRwraMfBP'
    b'c+l0WXWJMo7JYEHKUD04Zo96Rn10dR4Ya0RaAhB6ECoEhNvYxnxdlpe7LVie5cUwxG3ppHrwSwtJLP6kH2tiWu4riGBsruCR9R8v'
    b'uLegxBkbS6kBKmNLWe/sOJmASaCqpT0jg7Dri3Jx2RO2VlNwtXGimmlvhRL57N8M1/PaMWqLmwZqW1z+i9OTV6ev38y/OXn+/Fcn'
    b'z/6e+CpDIjUcRQGdGXYVyeDk+XPpW4rCL2v5aNVqISBtoVDvwc3YVjdhC0BZDExQM6HZPcYqXaNd9GVUtLhVNDGBTrULvKDINM0y'
    b'g9/UTaBSmtbF/azvqNBsYLocJWKrSUnHZYdlm75BSfzaoxxfoKJnxNC3nmccgoISOCg/5FrFIPewGPRHPvbt9bgQHx005j3a8K1t'
    b'oiaB3EJe8KwYnjr+lAHTrMiCUeerhHgeLm3If9X02Lobxg8+daxPsMN4TxsSZgYkJcxWjXwp5cwzwlfAYkcI1iYAS76aGYNx5Dfm'
    b'qeIamobOHed6d193YTbqMk5n36zmONyacfiaXQWNkvHTL6USgMuz1/woW7S+KRzb1fr+aXpd+wZanJNczb7tpI1YrKBCcryqciFz'
    b'+AT+xiazTNYNmVDAm46pvc6Syg2ibTrwmE15KcCWJrKKgKmqSB8hlT5CzFlE9DZWwts9TGFxG8l9AHhsAkF7C7nbkGOyTFVsYwwX'
    b'blCd4ggM3Dr2FpTbqxYNWyEExNdmd63agNyS87Y+wGMTjjiSSpIZtuJ18db8GanhYrO1Zn8z69psFqwWVEaO2kHfgEm3dkkLmW7b'
    b'PDwasakS3LaBRPQmjEN81nShkAO0DwY5Ve4TgcBgyN/FvhVXK6LFkS2McEGb+g/DufvGOxtp4PHtnoPIYxZwcFMykRbqqLPaMVK3'
    b'WFReJZNMa1IXAoYpuK0KZwdEs1sX01/EPRZvv0W7r8VqIxDoevZJeFkNAUVsGQ3LRUkZLPf2Pbw47uzo/qdi+h3fDRYtkXDs6A6O'
    b'9CA7rRsyorRcY6IeEvfoGXHfHhEhh7r794CI2XjyhPZ0STEnfhzwl3Cv/sDdqS4MJW9gIJCpJrrXC5txdDtxMOUWL6uF0xWr3J09'
    b'z3w3trIKeGvu54n2jlW7d/AuC0SX6xusAVhkdi6QBkd6VBGhi/RJ1jSiS1giWRem2Xfxm4nR9FZ/GWSzjNHhvTWAopoJc8L5ed41'
    b'LbD/Zk/YHU442nv4Lv43mtYY3Kilj3TdOPqEW7DXmXvYxRG04/+xgUeB07rV4zl4YofmwPND2CPiw9jzS3R+ezcsiL4gZ/u8mco3'
    b'AbcZcpkOzJmJWINje4f6pQ1HZHbsPsYIDe1FKbKBLVholXm0slVKze1UMm0JIsZWtuWA8XPczV6idEdTFWrBLhQ3/DUhmv2NAewy'
    b'JA7yqXjr9CDapTjegWsfpVciYDZnT2pPU2cNUZvNB6yvbNjSEiFsxKVBmob0nUC1iUIXWMO6vhOqsl3oAqoN7Y/jFg3ONERMGoJ3'
    b'jO28zn8PCAo0HWMqKSoXrBGzzmPi0ccyD+E4IQi7IEYjFoZgm+EJuwCHQxmGoMbtCS2AXbaEBItjCXYC0zEHW6DFrRMtYG2WiQpW'
    b'3j1leddMBQMXdkGNRTvsaMcMa9inCScMYgd0iuuMsZF7QTfLt0PX96VFuSug7456woLtlg4b6tqAmeMCI8a8G9Mi1ToQL2JfbKNd'
    b'm20xgqHIKhAYJW/S9XxXd+NyoErXfKtoCuBhOzhO4M8022229b6CPzjVLkfHLSVMw5gKIu9LF1njoJLzkTwO9NcCpIxoAqD4W39g'
    b'0uAmAIs+9QfFxjmhAcKX/oACXMPV3uxCXMIpH7T9GSdX6J+i8CGoQFTAIqFIIHLQpbit0e07EPAjJp1TQbcM/jYYVixiN68Dbu0T'
    b'UOyj8e7Emvdj32FVISTZX5n4vzLxf2Xi/xyY+FD4+jBzHi1ps9rRYop3jpdQHHG0iGJzoyWQeY1+jbClreVt9rK1qM0rRov6jN/B'
    b'PlxcfHYkL3bQl8OKggqeTccyDuRfmavo81fm6k/KXP1ZBCb1+aT7C04a3JjoarKq4tFJnSClsdikxhCNdvrGI9UGo7HQSJ988iB5'
    b'3aQrkTw+n+S5kdPtYHTs6lgCQngg21WeCdDQVocHBwecL6uebm+nbj6OFvbZDV7t5t9oyXsRSnjx8ZNM5LHukCDmHpJRBEItOdk6'
    b'eFKkB0k4p8Lh9BHkM5DOGqtKb/vPZbID5nVwXpzPR/ozzUL0e25AhlQP2Cy4f7CkgDIWSK0yGzdclGUdCFevVClk/BCPeoSmDpaN'
    b'gWPzIA0NnEgMgGPK4dJuzAyPY3/R+a+cSLgySJFT3ItYZIfVCdovYNyj5cqP7W8OSpJFMIC02zxzfu4fsjdfBkL12h3Pl+0hmWEq'
    b'ykt/+BRM+INC/CIsjn5bXkYC/vp61LtEikWADiJy/DhSxlm+9N0KeuOEjJolUBFt622raVuzM+yj6HWsw51WHCtx05xHjSA4xfdj'
    b'O27A/Khm5PaoVROE4vcSa7gnBu1r6dGGSJaJh2QCIgGD+6J2OL4km/JclLXArAGGmUTYkkEbPpvTyl5jal9LUJGEFooAmQFnQgMM'
    b'2UOZdidWYZfcOR2JRdJsiTcenheQtjmwGQVMqZ+SqAaAWLNuYac/t3Kqgn2ZtRg6UZ5wz5bPHZzVfDhoqVgzF+NXubc29AhDcGC6'
    b'+8Rv9UBoUuf6g1jUKLScfQwi/BtU934MQDHjPDp2XdYv31PFLkPT1DsEbCCuK5usWK16k0q27I7vjdHHcAXXfrC7AhwLXlkmHvbA'
    b'gSp5g3HMfby5seLt4xz5knypjwpFkB1ZWg+//eC5975lP0fw3TMQNlHdrC9BuxRYHzRmhiLbdNa7mLqhg4L342gZ5lSdAr4dixtY'
    b'KGhBpAsxt28suxqOS+0xSoP9TiZqMrhy32sBp34ZmHtK+vQeJz+ADuG2rBv8u/7YBNAk/sg7JNWeYpYr6Rg8GEkf7e5EGGFrcj8g'
    b'TuAOb9agKTOSYWn0oqxYDkCeiTASxtJkmTtbFXYA4xKHGzOXGEHpK0/7IdK3mc6zKIhjPGl9TrJQ3JjueoZ9IeNcPGmWkTALHl6J'
    b'129OXnx98vzlC3ami4RJRtMx2O+goKZc0VbOcgyYrNOGD0YB+K9ePgf/vR9MjGMXcI6+5bZy7L/ieFF24+Bysls3+fw8Xa10IbND'
    b'x/ZPiH3l9/D0xbffvTiFqMZ79VHn+XI+zgXuI2gTDAsiXdfV3UTzfmVnSLqqnRHeqigpxraCSDcCaHWRpYgnjExo+U8kw6YVHL3a'
    b'S0Tuu3W4Eaq7Qk1nWiaB3WyJGK0KUeSWQUtg6eyMwQXzb5tA+iTh9gO8hNp4Lapc1JQ0FSW1s2yKf8dJBlKbGUVm1+OVxu6Uoq7a'
    b'UAq3zmmAGQbU2jWQ9UBqFc8FhpifL8vFrkbB7jq9HWYoY9NtbvJCVFd5kc835UYUzW4zT/Fw3qvVABTVILVllta4KQ8pgm11TmED'
    b'i5xxbgIY2pRbdg7wsZSu/qjag2DbvoMUw2DRBuxpfI0peFHRG3VWAlELA9ZiRJBaYN0RhFk+8FBb1aCL5vGBK6kz+yOnPkqONfQ0'
    b'r0XyGxDAnQLmDpeDXxeXRXkN8cnlfDFsKcZ5Zzb1nplrJg+LEq5GbUTwzKzN7tyA8910ZKwmoSchwCbQgl4aKznII29OesMFzqTg'
    b'9iP2daS2t1fPCjNPWCkjn3T2aF6l1zJ4aK2akD9duEA6qLI5d4qYVOX1HLOpqzmyefZFVdb1vCbqAVfq8nxXN/Pfw45imuRcJw+n'
    b'RyDPZxo4r3Hm5mU1l27A2dhAB1ZmWBBYI9DadCUgmCOOqhLFqrmg2a1z9JRzwR10daiLWoW72T3QwXkl0ks4IGvR7Lbzn3bpOm9u'
    b'W6BOePRdYCFMge4r5072IHKMFkQERlES+HkHj+YDgfVnfy5Lh2KG0+GyTb64FFUdCK1DuAd5UZr0ErzL68tjvZHGHEyKKGOyzjd5'
    b'g1QRaaLN0BZlsS4X6dpr1b6Zb/LGIY16w6tX0A0UD9WX00qwjpPmRc0IZwjkfQRuFabzEhKwDN1CAUrI5RIKxbM+mCXdEZEvJv1A'
    b'lgNBBbkO7gn8OfsD/ivr2ZobkH4O3XZGH9Bto2FH3R0jM/Z2l4xMRGNjzrLIdlsxr8F3FK/9xS3ceushfB8nxFktyvUs2vL/z96b'
    b'LjdyJAmD//UUOZD1NFAFongUSyVKlH1qSTvd1t1Sm6TZb8ZoNHQSCJDZBWRCmQkeXVNj+xD7hPska+4eh3scmQmSpenZWZpMRWZ4'
    b'eFweHh4efkxmNypfjpE4Jk8bcnR4VqrSLkBI/virrSu3lTFvAIyiJ8MW3V9H4yzfsf5thanBJ3pH0m6kswJe9fi5MoELFgTcswef'
    b'kzqM5LTJi7IowXWPSSQHWbPboOHaPWkY7uUVF0buYo9ZHF/xzUodc4dgrHO21HrVj6YO30fvorniIAeDV559TjgfywJtRnTYRI54'
    b'9ssuL9tircaHs8/gEQpfQ0oJpDPtmPd8N4Gyj1+ds+bgtswuaR1zaHRB8kQIhKi4rGktcCBbNLOLJCzTrLguoXUSm9jGp3rJPV/B'
    b'AIZveUa5XucuUnIes952ms54hbpa02ZPKxwosDBDNxXIfasbEwTRuIr23kYeE7Sh906SnWef0Tdn5gg5yerbfO3FWDvS95ff6R7/'
    b'iLnQ+sItbHN6nMaItvC7eZaeuJ6wt2taQWtn5XWFASa76ypj5D4b0oBfjf57awMMD1he+EEcXA9sfIkIUCJGBfpxm/xWze6qUe15'
    b'WHniiQBeefy091Jvd6Tis+sMrajluH80LiPXrix+2anxhB+Bei2BnWryyL7Mjv3r7o+7EtDThXf0vYLQzS28mjZt1t5VplfVKvvh'
    b'h58MTeGhEt6JzYaeQd423BtV084TYS2YWULEagNujhBNbo4orrZgohF6TB3P4K7Tiamt86WyWDAJdFMsnRMS4rpM9Zaw8lPUB4Lj'
    b'g5mi3U8Il1qt6ElnHg7FHoWwoT18dAT6jYjzD58rPAtpgbJzPmK1IX70IfyQCxTFFKcp2dU1JOkTRgeU08GZHRggF7XbM0rVsQTV'
    b'fTtvFjdquVur5XypT87v8589JoxjxhO+dDezn4uNatp8s2U3s5tqDXusmQ8JylGrthfO3eNIu3IN8VMg4DgeMLYLU4w2Xfif8Ygo'
    b'Sn0usCMPmDbhmT2ovNbRqgv95yR7kR0dZy8zDYJNMxj82ywI0GFBOYvAvJVv7oPsiBlBmum1vdNwF4V+QrNLkoYEi1kGvdlgBsEo'
    b'7z3Plm1wz2JgOzStQZMHQ1Joy2ESVwbEgaXjZQtinehcCMlCUsBsu1PCbGrvk+sWBa8HyxyHEIhq5MLPoYTMhuFdTGt1OwdDGDuq'
    b'WH7mhmwkOlWvdoduNlJ4OpdyFUoJ5yQriEacHBu75OHs6Hs3dqXnBhVUVqDM0d4lNug7cBsgQXPTtvIH/7FTAxwDnlzbiQ2hzpAS'
    b'j0WhRKMLnSNjnAYGHJnzUJAI+vLN1z/9fv6XH3/4t3+f//yHb/743Y9nMKxhrXZkLddEaLx3xkQjU0b4UudIBIq1XmTjzoPjFfFp'
    b'LjClCBqOowKtgnTZyFCIplmyMHPFCYyMGZv7/FK/tZifGGPHbxILWFRZiXW8bPHGzcXXc1+cFbtQ8A4vONKQVbU17KlBygu2ed0C'
    b'e+3ZAv1GgXO32TjOiKeFRgynDEh4xcKGVy/Klp1E8IO0/q6eZneYFNSxjyAHHS4HGtt5Hb/w/47vaFAtwKZ7V08ml772xUNhpPxk'
    b'2LPeARsaAa4gjmcvsqIoM5WGBk/1jp+zbNkmApfqoZ7hXMdBvs8xhRk6OuPvl8Z+kbnj6HVHjSUC4RFc3ckJG48gCQpuNDPls912'
    b'q+rxBE7IgDKNlWfCQXwErwHojoyd03/1dU+DPWcH9StYsp9eSIu7uxQg6LTojmRgaWR0bbKZgVMjo5trbGAp90BsNaECAduHR8yG'
    b'OI4HNogqlEe293itS4qqEsokuSSpV7TeRUpU3H/ZBqigbWraYQrrR/TdxxEdRizYFxGCqotqCQffXV6DDR6c8h3erGw3qX2r6dhp'
    b'AMe0SX0MlAQGDBgnPyVqQiGaZSZUULr1QDEVx+ZJDgFfxxw13cL/DN8E6Nq8Xc7Kqo3fJhIBA2Oxqb1jvVb+BWJTNA0p3d03OmmM'
    b'AzSuWNN1aX6EEFCADhDxS8qYV1tVjlHDOCV8yzZ7aW5NS7Vu8/Eyf2jOj8AdUF/54uXBlaIujN9XJBy1noaX59lRKDT7ASvlhL40'
    b'Cou7O7j/as5TeJJ0ZE4vDOvEHEFBNUz0C+LIErU1acFMSiMKco9ha9qYXcgnFxrjJRkqaKEC/REmIR596T+Pdh8xsOZQDQUTzb4N'
    b'OBS4U6dtPNrliwQTctPHOi13kShgzYZDttdCjbFj8rSsoNVvgwaQYogwBN78iycPqAQdEW53R6kHeEP7JHbXWNbFqtWtN/Orh7me'
    b'ar3WYws7jdKCeBNNXG1Qe46NaW/T3cZEL6IL863kHFo5Lcd9a5ILsfYMYuPVBh6p5tsBqgCDhG+xKbAW2LpTJtc8qHe4+XXA27wO'
    b'Yh/swLDlI3YVN8q76E0hGh51wA2Bjp8AVHPICPw12ujY41hrXM2SRoOXVI2Ti+GPGJCmOo5Uf4pBG72ChUVyjgXZIPZsns9trhL8'
    b'Go+0Eoanc+sGuzfgRgNCu+0jYjyfePEPIloMlcrSdxSMStot1SfvG891deAOQlaXvlwFsSf0JmWmBQAWmCVG3p1+Sr4lZdu6Wu4W'
    b'CtwUiSuvH7RevYF3JtedIU+CKUiOB90asePCIdsPUC9apjSi2CImpnxpS9jmvpzMFrsNjGccq00t4XsMvs7HnnleBC0iIhYDaV01'
    b'oNICN19mxLyti4UxlHCqZhQZje94ubhxKip9P/Lw+iuJwhbFUMH5KlpVo29DM+YWD54YCyKWFly1McmVau+UKknXGGqBvF6EG6Ce'
    b'ycVJCb+RipEjYFBteZ5iD200lxppvw5jFXCpTeqn7fQTyGX2At9taV4lsSAoF4HwwycyTPZW1Stwy4Yx6a/jGEVO3eSexxvQb9OE'
    b'4yIel4qJ4hqHPaQuZ2hvO4mg4cdNiEGUGiSovuQljPjEjdzc1myDqWdg13CP4v3YRi4xKC0yCz8Qm4dHn2xQ14VEw3X3AM1ZYqPL'
    b'2DrsOchCp89QUytQtxOZ+dWAnpjBtP80ah9DSeDTf4DFdquQOfy92I6j7wkXZwdHl2CPFSs7OrvUT+maH9G8REAxcsGxBcX112ws'
    b'QnXd02KjViPBReaCaDA2SdiuDvkSm1jXi2W+9aQc5jGLLDO1khSFTVJKbEZSpCADtLkBd8yte+TTRAlvfB5+x6CZaaj7eFNATvAH'
    b'XahToghTKIspap2QOg2lmOEzLi2vTWaQCo+dQQSlfgmPaq8+M0/yD+6AH+M4mRBgGumAHnTaB3jAYMDYgnmLAq+Dx1xLFS4Pxd6y'
    b'y26wk1704Ogye/GCJuUVNTQxV8FipVuG62Ls5mwb40EWXUthxHVrzpMdZF3R053ZT2xgeZug6Ohpl32VWOuJOKUSkxeJSxgeW9H1'
    b'tfMbO/q7lmnoJKfgohPkAXfScS+spOJ0P3omkVV0gxwy36Ho7E22VSqF9xX5PsnlXlbJl3lZ5Ez+JLtcSU8iXhB/l21ap+j7p4ii'
    b'z6K7nF3X1W579RDeQRjq0pgAhrPvB/x0s8i+chGLfONdEXv0NoJVgoZjTZkqn2a/yxsFhiRF+5AZce0lpCrN/nIDRW/y7FX2ZpEt'
    b'i/y6rJq2WFiw9iYnHdyn2Z2qVbattjuQMNCN3WqHsr9qeljs6ls1WzS3f82W1V0JblP5BgTy9oYO10+zqlw/ZKpcHuwaVWe3hboD'
    b'I8f2RjWKdaD5Inun1Ba+b1BtdqMeMnVfaI3gp1lTwTdUGmX1rjy4VXWxKhbocpo1rdpCtqesKJutWrQZOkipOkM9B8KQY8+n2avs'
    b'tlofkIgHq1PVTQYO5mApXquDeleijT60Zc0ssarermAoLg0sA/tUV6J3ePCF7SNWFnCGaFm0KuO+fiX53SXOmsPko+9kUTK5c7Ss'
    b'8ztYy/mVWoFdMbI1jtUC5KvWXE4iQ9yq/F202qKoF7uines1QiWVCMmRBlW3qmwHQbI0RwJ+aSHW6lZE6ICyti7A7T4y/6wiOuhj'
    b'7UjXb6u1ya4UL6TcLUB38+2bBS+t1QI0gFrnMl8rs2ZMqCpWct28Oxkod125Nj3nhCtVBLzE3KptdX2GEgTT1lzwWsIUUT/ISON9'
    b'y/3PGavWXrXrBzNafSmeGg53rv+dZpzRnNveTLzslHFjv7nZwU9NTKmdGWygR21n5HSR9nrCgP7Qqjq/WiuEluBa/Wq6xyrJyXO1'
    b'WOp50b0s/ddln98E+oQY7wh7vaVHC/zF16tErZzDeZ+Xo2n2mRbyhJ23u8VBCDX3x2MaitwNR9Ps4mianWiRhGLV8Ou1tvh/D4MV'
    b'xubCzlyXfnWeHZmQJAPsng1Fo+t4j6ur3QpDgNfVtWPPqxEd4acLUFn7yty22r53q/rBnmBN5swOVyOtkG7O3/92+tvZ36qiHKec'
    b'9icfnPVgc/7em9EPE4irQqhpotBfgfoyKBQAmllrdLgQsoGuvHddzky9mf7Yfo8UhFbBIZC2D7aTHVF6pjQgmCrRfOvUd3Ya7c2v'
    b'MGwTsEmQyuIJa64SFnvJWYEf986xqZbqPL7LuaQhK2P0Jqq5Ku7V0o4/UcPgVE177p5hErYs7OXlfNC7i3lxSeDThzUTpnF53MIm'
    b'6pFiFC5ONFJuYp0Y56MIIiQKz0IU9kQ7887TmKX2xhpvweC0NsTOdgJ0P6dEO9c+tnCWnU7VzbRfi5ESgvvkJOEF/zW7ZuOZPtBs'
    b'Gf4bm6ab4dN086zTdPOoabrZc5q8o8fM0429l3uySTweWJIx9TIlD31I7EnO5HMlq99tb2plOFNk6wmGZCpF4DgbGoycs6PBlRI8'
    b'h+fM8qZp1plVTlsHxOwDfDa1fCjzDbiXo89oUd7SnQT8/hJMRstSNm5vIg2CseSPR7R11Q0Af/MVLXPPaCRpkP7YhsQwLcm3BTmK'
    b'wD3U/Z9B9nuLrh+E97lkNZ73OVa18ZYsVNLU32xI0YK3S1NNeGDJNkxIPRObWHdtahGYTAlXu2INMTkTEpYBH3Kd4rnYo37jDntP'
    b'mH1xdQpcRQbV6rzADbpb9d6mwDeUj1mfLV6waJmhXoajS61eR8wpCT2N1X5mF249AHQ+irlKw4MJc/ZOeTFaNH5IsUeOFMEd4yC2'
    b'h6GYO2yD5dIElJWK4Z3yVoLy98xqVQuDH2ZFQ77uYRNGc8NUPLFBBBF+XSx4ag4tda1fiJQQnPUzNxC0zVxchF2+vEzZmAjMyPMj'
    b'HbFA2hvMaGlQixTu+/hOCeH22C/sKHIR79D3wDtcyNXcAgbRF0TX3R8X7FcfZZjkInF/kgGTfhVtjI2bMkTx0Ow2m7x+GObNve/N'
    b'v3OR+Hnft0LYUxOX0ZMyoAK8UoVCJls+Ie3b2HoymJ7x7tNyu9wGgT926BMbdDDh84exmK1ChOgglmsjJf84owGLTWfp8Z4Mscim'
    b'KYoV2sxBXqF5txIjisa7yst3CgOkSNCk5Ac/YJpQ5626fjDP0iZf0j5ynyf78YxXgfTXKwHyWQEtOA7LuDgFEP7qhdcREb4lrkKx'
    b'oSEvMJy2l+45XHTR8OQyobLwzvOInsFQv8QXHWs4N4bSWFgM13u5ql66LIElljuL4fEzqYcILOFGEQQJz50bkmGOw2MILKMhBGzw'
    b'gMiVncXni+0ZznL39dblfIzbM/f4J+5jw9yjSxv1W39buS9u9e2Ku6y9sa2IrkTbfvep7lywflPtMAEob88YertfzQcPedVmo8ql'
    b'sIePW9jLnZbqr9g8Rsyze05OIfs8wPfT5GBlKHUethCpKehHa7OyMrQ6AVuI1hR0ovV9B6MucOmdrJaDw0pGg0t5ORPjp4UvBnya'
    b'/Vyo+uBwwdIaHk/Osja/RgUa2h1wtZMxcnCmFAxXs10X8J7bVpkfnD24r4NFRvaKVZbx2BPwGQ+9HoVhGPNWJ1zcFlu1Lko12z6c'
    b'Hb1+ffIZqPh2+Xr9YFwKQHAtD0i8WxVr1cwYnr/U6raods36QduEnBAMmZ8cZ1cP8Co3xtqT7Eot8l2jcJZWxbpVNUP11169hSfs'
    b'/TWr1UrVCiw2s5xhIiETjWGGqkRAAL6u2qytsny5dCM09DdMqxxAP1Wx7BCmk3YaGJa50+uLGzWzI5ehaSySaRwHq9iJOFnVcmFU'
    b'cQs+HKmzpyadTdMg5m1wSfbdPXWSi3Pr0D34+MAmNF/3GtmHsw9sSHN6r6F9eH2koUBHwclOykMyQbpVZDgJWoZOF3WDqOa2ANLo'
    b'rfPN1TLP7s+iGhlsL1B+3JskfxJdLADjZNC4TVkk8OOQ6eoOBmncP4OeeG9DdmuzA7ZPTo34iu4hnz6zbPpryaWPlElDedR4HdiZ'
    b'j9XaWzh9VsH04wilH0EgfWZhNPDRjL7feDsp9X7jgSU1mnq7+XojvgvFQ4/p09TU9BLnQC9ViQu4fK6cOYOSaeCvvbp+63ECcfK5'
    b'/mvK9bdLtVJlQ65fLaWeUSUY3EGcTZxiplX/NPtWrYpS2zF7mcLJMX9dq3z5kBUbaAIBWxDHiybbVOCE7GQ6nhzG9WJTlQ0YxNre'
    b'xHLY/M9ID6JrXlXlDjDr4OsiOa08ILx0UJCtQm67INnU4ezYu7VHElodHM6OGCLau2FAZDhD+Y7Y4rWgtjnKKA0lDUKnPhBq2Wkm'
    b'6+frdXVna6NZYneSscvJJJIboq9buCaYbsUFuP8Vu7d4WKzBDHMBdK6Tj/QFsB/FKmn7BbPpt2DgOC8as5vHutJa5UtVNzfFdg5J'
    b'MkbTTCMO3J+j8IHo2N3Rupk324f5yUb3bnbdSgEOfv65H8kvv/zSiyRU8Q3q25tOtPDzH8P6140oJrMCacYmeb7NG7odRYvj+U8s'
    b'MkkWujJW1BJwDGx2d6NqNY6252VJSFDswPaje/Jj5jwKQkv7G1mnXNBb1wX8+fzUu4H0Jf4ZlrgvkldoYBeJmdgeHs0OH9/DdH7A'
    b'x/evya/FBL7et3uIwOaKenqHREI93rHDfTvWlaPvCR20GahY50727dzeaawGds4msOKdC5f0+VKBDUjZJfcqbS+4t61TWcD6s4tJ'
    b'ZLQj0nP3qXb+O3pz8N1rppH+fHJmSk4Pvn71uyxfb29yo2j253bm4ZSM8wzteg5q1Sx2kLqvVNlYy9UHINmDZ51m0RMfE+3rolxp'
    b'gj3L3myqg22tDgyZaIv9bLwqwBIHPAF/+v7bP1LNEF/Z1g+Gps4yzGVW/F1lCxwrlEIym7G6b0F+r8rsZfbjT3/IXmabauMhG7pp'
    b'5SHCiO803BmxE+cJvNXN25PYBSGjvjGUTz8A+GLwHh7vy2klJtex08eyCrq0eSdUqMQbfkBJlB05+YbO3X3RzusChCuWj+/14zsI'
    b'2gGTZNsif1IXsXe0MrqPzzOVDO/VGnRqnRkOB7DMZ81wSAGMuEqWXXsH5OHxUsbOo5c0LYS2haqbUEmD+hiTJpEuQHUO8QI7lkxj'
    b'NA0gZrwDfvuvX/9p/qfvvv72ux9NPCJpklfnd5hEmlsrQv4tMAODX8DXvtiOybEOPlACjbsZvl2OR9ORydoiDKQsDtTK5nU7SSGi'
    b'2rrnYBSJZRyIcMEtMq/bD3yaTS3INC6GKvPQx6bqGjTCwxRk2vbDpZ2MpuIlA+G48gvLOjNRjxhNdGY8vhCQmJwdlPXrh/FinTdN'
    b'sXrg5DXN8vsCInB5kzyMLrV6i77CLZAuVqIDYQ5JjU2b2hflXGdphFfFoyl8ESm7PHM4n7IRAb4546llnCNOwDUientj6+vtB3xk'
    b'nI7IO1K7jZrO9uOyt2A2H+HdV7uachgIOzqB/FFmLsRqJtsDYfVe35FB8xlXqNKDOa4p5RplLQsbRgM4sEUXSsmQsK4vc2FLXZbl'
    b'8W21fffohNj/NZmvubo7rkrfO220kc4/z775Lrs9dvL50dsJjK9UdbZY55ttdgLDPDmcZf9HUTctgMOjTmHiZKw+P8lf58fZuliB'
    b'Evsk++Fff/7uR6rbZFe7FsNJqyVptqtSfZHV6Gue3eVN9v35yWymXwQ/1fYbILQXS1W2BeTLNbHvuCXGdV0ssXpTrFXZrh+ouaK8'
    b'1ojAjQksI04y0NXMsp+Uyr75/dff/8t3f/rhX7Kjz89ODrM//vQzyeyzIGtfhBPYu2ZUYcgolakJI68JSfp2LwmkXORvCbD8/YcF'
    b'WgeG1n9Rs78oKcB1jN3TgA54e2guUzQH0F6G2xGv9jN46IDhalzASPjVH7UbuFi1gvcCWF2Q93Fx9d0sG2/UpqofXq1Ak14/aFQQ'
    b'fWELgtOELGNu8luV3ebrYkk5NJG67lT+LsMQGXOIZPUKYpaoVnRBo7M57upqQ9eh7Kpq22ozy75Xd2bVKNH2dr1rshwSW5TvDmyO'
    b'UbxhamzYo3y5Kdomuymubw6oSxRAqFbXeb1cqwYT7PHM8tmrLNI1CkADq8dneYntNRAt4LctMLl19ldc4L/Osu8226LGOayuGngz'
    b'xSusRoe31DH0PTv57NXp56c66Wh2MnvzuXm3Pt+VcCZfl2CIA+tzpXBtqs12rVq1tqtwv1jvlmqZLVWzLVoFywCAXZqec7DV+X/+'
    b'r/+b71qN7q+dTwx/peTW0B0kW9qbAU0Z44+es5nXkRojRvPfZt8ee+oJvLKDKgDCv0B7N3m91KdMVoF7gGuIevhp9r91TB9gc1O5'
    b'cd6pbQsRiWDWdluywiM6WRfvVPb1n//4YzbeVJv50TEZ4H2avTx5ffibabYs8In4+PAwe/n5Z7+Zosbgs8/INeh/f/uNrZa9/Pzw'
    b'+DfZP/3TBKedLNvy2ky60Ymg8gHWknQ4zRSlOeSC2d+rUjUzqcbQKusvcerMNtqqBUZCAos7MkCgME7AvsGULhtDKB4w2Dv8TZZf'
    b'Vbcq+/PXx4eHwBgX+QN9MuM8PvzNFxnCw9BODw/enOq/YWQnm+zl6cHR6W++yG5yiLhDwrcu+ip7eXr4G607+TT7PVsk4jWNVbtc'
    b'qXV1R0cQ+Mo2cCV1tCXGPJS4RCVJXR83C73l5H46elvA09Lbjy49vfv2wv2qylUFURz5njnDB3Et43H0NTBYEXwGhwi9ln6QKCNJ'
    b'V+6yKtcVMC5/5PzUws56opI7uMQM4JndvJvVStvH0v3ZXn/pPI2/BJkc7SidApYnpJTn5hUmIx86Fw1Kis4S0l/8Z0cmdP3eKtuZ'
    b'PK3b0aVP9S7u3yT1EghH7hNdzwGTPnOx84Dzi4Zjo+6TuVDDY8PvzIldBHYcvuteQi/UvaQEadnNEL7i9c7DQHpHX4HJOtT5Gg4d'
    b'Ha7s8pTbf4RYedeq3BWlyrTCUduT6+WBw+3Hn15Z3TmcndndjSpB5vewQctZUW53OtpD0Tx8QeMA/cM1nCEoUiEcqjUNI5d6cqP5'
    b'NHGTgyd3+NljRtKa1ADrVwNWUx6lEvmmIInkzbG3nJM93+f1IAY8bUGfQRh/jubqZp4vFmqtMPxoGWnnUDYTsJOLTsqXWo3xmBP5'
    b'l/7OmmT/EZBCguHHmNlevQl4Dpckj68isiPel8xOAb8RnLEDksAy01/uovDTu2JLWycmjGlfgaKB1C6qbLNxtV6qOlupHJ/nICaz'
    b'Yg9KoMCLPWL4zAt5XigNfeUfwb6w1Esr6ReUCN4KznOvB3QMiI+iJp9XQuCM2bQjDRmw4XCFDVtIHdaqTrEOPQHfgDNJTpAcjYkI'
    b'H1oYRkf/yy4vIVikPWwCcBxjUWJC8cf1ybRBph+HaIJ+Sv98/nnIKcMv+vVy5xJLSfEhYfMSkRZMV8bRDnqcNU4q8RnqJepIB41J'
    b'kxrbAYYd6LPi0ugHmFFEUUPre55LYkqit+a3EOvnsSMBa4blvFWbLTzVz1e7tbFAgL5CEPLHYqbcJ3ibnG/y08OPgvb48NnwDnoP'
    b'ja/q+omrmt97DYHB0aNH0v2o+dFGQM3am3Yfp9mb8UoBbQDnjR4Vj+QnjxJCH7nj05Lo/5S9+BGZ0iOuV3Yp1+34ua6IfbsjIvRK'
    b'IvEkcEvh/xGcof8R2Qg94ndnyyILznj8nxYnXFUGNb5f64l9H2l973H2XDOSM/4EfQ5o/U3MeKuogyfIqFDVL2oY9/RoAxcL1Mcu'
    b'yFzCfIesl/7tQqT8wRTNBjwM4mKxp3rs9YjPNPe6t7hC13qbiMuATEKloFrutmCqu9GhZEpyfNI73djNrs8tDshAPbtR+XKM6svJ'
    b'4xcxQith1mtcYPjVKWaF3tn4SQIy0YlhGklfyTjbbdFTsUM52VagBoZ0K+YhHbdLs67Q3gbTVOb340N6XqUwxl2WQ8FBRaiAyVkT'
    b'C3puZ+2YxKc9R2rChsWAPsKDY+8j/KPokEKFzrMYvwmMXz6LJlMYve/d7YECx9Pwdkgc7jfvVcanIs9pzC7hfVurjTan9ZxnBUHL'
    b'opiunvyRJJxl/eehsr6PUsMKMT4cQnWZsMdcbyN4eJRUk5J0kxdoyH2ubTQOwMkU3ZV5SH3J+2h1aGWYb36v353n6jhBijBAqwKs'
    b'9o3DpO3Y5Mn9xFxnprpQuO07AnLR6xyFdd77tcbwEdQ9pJMw2QON+zRXOtuJe1RD3iuUHYHzqzAmIcEccmuaMzIzOSAzl0wYk6Bt'
    b'xyz7g7b8CKw+NLK1AqMXOtmqrSqnZHOCleCNBKL4SJMK7OBftYEB2ro44wtQSdeKjDy7jFRApmMMZpb9DC/n5GZhekYWNNaCB21O'
    b'XmV//tcDtPWcgAK7Vswyh/mN1Or8EIx3NCY0VIGX+WoLJgKFcX3+OOSI4hoIMfOPQpifHw8hTHlTeB4qjQzMO3sQwhAghoeg6faY'
    b'sJ24/Y8eO/kYslGaQXziW5/FjR3h8TAa2gCxeJENWJBYqpeU2ivYvU5oj82xFt7Jhs7rkrcoNv13JFOrHl61a23SIFbThXTpNEI1'
    b'o44ZocpAHNrMAy0t/NDD1iJVxgCE/W0vAdqe20IEIrEej45hDE3qYFKyH4h0UZW3hb5NQgalkTOtjxZ/IgN3xmOndd4C+d1Om3r0'
    b'R0sz9hkmumbPfQbrgNUZbGpjc2EpPW7R60I+04ydZyPNAIEBgPX3yNWhmYT+lNvZ31VdNePSPCnhSk580ItDHRILC9Sat0NUvq3u'
    b'ICYB43vgpyF5jY4tStk7IxtigFMJEusNGf+eg9HhXXZgcjnmdzO46E3AcwVdr2aLdbEdg1V7fX6kDt4EwxJvbeV2hoMYa/y659uH'
    b'MZ+ZKaZwNiKPiZbKH+UILl474h6ClBlEwD46o0Bmdf4wvjiaHV5K7JJVHnPgw9lnh6S07qxzIuuc6jrotJau6cLDIClSwO1bLxqw'
    b'm1wsvCgtmXvEFQYS/jT7hpsyfne/zcl7kdI8ff/VyYyMQ0AgWavrfPGQff/l+Qm15KEqyjZftFO02wWr0DxrNlVFL+OaL2gbQTjb'
    b'7woQmtb5EgWMpvKQWUNwyMOogFnAQ/vrV6evPnt1dKjlH5NpsbnJtwos0Td5u7iRViRAMo2IU5fae8FWJfI8nH12PCU0Vh8Y37XZ'
    b'uf2NItnpAOr0TXtjTCFK1luqy1qzsb9gTHPUMLF4xm7X6Cr9G8IR0d2mKM8PZyy+yd0mvz/vN4PM7+dNUV6vFfq+CId7E0Kqa9/R'
    b'ke32GRwqbSysPIaU1wHlIe245sFTMz9M88S2g420dEcGXQatiENGG6itWoygrNOn7jYgL8z0CcRUTQT3FcYifInr5LaLHs0703+I'
    b'cInwJKq+m2a30H9AXLRq04wnH+Lygk05FvdgeWJuwRe+J0t2np3Qt2SMLgN3lBRAwH0pON21VCJzDPbltdjm7Q0QPMhX+LtMKb63'
    b'40o2btSiQtsW9EMBdcQkZrWNLixTMFyrH4izbCsYNtru4HR9dZLVCtYB882C84qXs3WwE4mcXl0Dc/KklsDFuURJSceS8hz1tGoz'
    b'7aJngeZImSktKDZzYUSsQGwwRRpJz92k43QRbZhb0jMnECH3M5ADy3xMeTHOw8oTT+b0c+zGw/RSep/uKL1GFU7rrF37+kdjejyZ'
    b'mQTQXL+u1xLkUU0e2ZfZMRf2ikZlP+5KQP8dTMt49L2CqLMtXNmbNmvvKtOrapX98MNPzj+Gbv/u0Lc0PtI6uUWF0fVYok2nZGRB'
    b'0COJBMC/B+4Dc0RxBWmgbB54d/ocz8CzuhNTW+dLZbHMt6BYoNd69P/myYcjvSWsIiOnBwTS1HZWNKuiLFo1vjeOxKsVvMJgDDh/'
    b'KPb4gL3s4SOdgN+IUA40bV63XmJ0gbJzPmK14SA+hB+cETqU9QLqCJ53XdlqgjCf8TQSEBdj3ixuFMSsW1Kinu1y9n3+s3em4Jjx'
    b'9lM6lwgbETOWrXRIGlSTI7wPDvXQcDTpZw40+IbsfJ6NiJ5P7+iN1HWuehH84DAElpiQSWdeqmujF6+2xGL2a9FiG00h7sDhWwr7'
    b'qmVECdvWebEGQni21gVGE7nAPQolgLVv9Kpw2jW7v3upeUhvXAPYp6PTCftH9y3WQ/CpqourHX4JrfOfpZPxNkbmqkr/7+xl0+at'
    b'4rvT36dso3rkCYZei2pXQgBYkmoPI2D2Lx/UeRuRS/E1xiZuVY3CpN2vUzTML/zPKPAVpZbymHgLwg3hmYE2ODsw9fHPSfYiOzrO'
    b'XmYaBJtmMPi34V6YxFebHFyrMT8ED7Ij7jireZELu0twF4UON2H5VxoSxHwGvdl0ZRnz0ot5/G+HDgo8o9cdqsW2y1nRlPk44KRY'
    b'Ol62oN0VnQshXYM429ICH84d75PrFmR+RJfKkUOI1OqiL6MynQ3Dcw6q1e0cdEt2VLE0p40C8hrgmm832GZjE5uEaUidijlmTiHO'
    b'OAyeGtfA2rYatZ76uSvlnxFb4sj5CP2JDD6UfP0evv/m659+P//Ljz/827/Pf/7DN3/87sczOLA/DGo1kdyJUQP8A5ZNY1qsKaNA'
    b'Aa4pBWu9yMad4s4rki5844AYZYEQVUDEM1M2MguoiQclIbelZArZqAhhrFuWnn4mJo7gN4llvqpqe8UaL1uXdpzlSBb3L7EdxCaW'
    b'KztoVW0NK+uQKQ/bRW6Bvfb8NIA4dxuXuoPYtkYMshFcSYqFzb6mc1FquShy9GBP5lcP2vInfgoZ8UqfQTLxn8j8d2fUHZ7JUwUz'
    b'5I3/wv87rpjX2dEg99/k0jdp8lBY/5ZUsGvWofk2f1hXOUgDdXVn8lDhVa1YtJQyEI3Xqjs++TYJ4xmMX+7Z7rm9MMMwET11BwSK'
    b'5IKaPQAnoBCaPfNPUbZvmqcglv0ykeJdTEIC5Pt8Ayjq6u6Cfr80kxxOLRpxIRCe9dWdXMnx6Ju8uUFGYiZxtttuVT2ewFEc7DzN'
    b'Y/xgirZrEJexqk3n9F993dNgz9nBfy3fldVdmeynVrJaLeldMjlWfqffcQwsjYz0GGZgk9TIrJVcMLDOVEyRZyTRfOxtu68vkTr7'
    b'dywR+fwsGy0esUwAiuNJoO0dU6JedFyjnaaJQXPuG4pS9onI5AcWpfutg1893vVUn7eqLqolHMN3cLulW8LorHsNgaQfVxGYb778'
    b'267BsEl71aUNpx7T10dWlWcGiVFAqKNB8LXKm33gnXbBbNREeYrRxNUjFDxiHC1MYbJmFTqLSVdSvSAdSWiS0J820M6t/ylRM9fS'
    b'cE8yk0B3H8fmyar9WWPCe180e0zkItmX3bDbJFRw8G7QPRhfyiybMxGoYse1X/P7HAkJ2+fEuBPQewy9I6DE0NH3d2KfCYgkN7F7'
    b'I3LWpcH3mIQ0ksFHiZ+m0bsE1SrQe+R381QZPBCStaH7RjKtq7Kry6ZLac7quMvzXrVDbV5ncKB0Na3ZI1UaH9Oe97QCnidxBPIU'
    b'm4M96hifaKeEb9lSiFpgWEu1bvPxMn+ACJ9Tq2WLlwe6nboAg1AZOMhfppfn2VGoHjG5OcUQ8rs5DkPv5sLTzjgtBwARtDcH9hwG'
    b'dQapxwIAOnjjAOj7E3uBgD0RyJ3/FJE7w4nY1kUFD+8RzTHlKdNop9n70WK3wSQ2h2ALrvJ39MeHiHP+TbVbL5GApt6w5pu8zK/D'
    b'9xCgNXo8TKSX7rwCB10Vd+nE0UlrFC/DadE2bTuTaaQXFCelC9aKQecJ8SheTbyeeFVFWU9199yRQuIg4qjijxIetjhQJHV38KVU'
    b'd/PFDtTj4CgDGz22DqDo1+W0hqiz96LF4NKERC2UJYakdbOOrOHdJrGuBlgb3qSbiz6ORPkN3Brdjgn3aIS/QAc1/aZeDUmcS7wo'
    b'fpkd0oEYYVRDDpFZvlw69dnA6uIwic5EZ72OGYzwV1vbY7Li7H5p2PndHRBVZDKSsHxBpLY8ctpLFV3YSvdpL2pTH3jrk0GHRIT1'
    b'd7PURrXGqS3NWS9GHiM3EhyM0/3967StL622bfpbiCyo+FyitUZaxS31nmptqF6brAtN6IXGeOklcx2NfP0p4NHvmOdRIkEMrDlk'
    b'OLCe7NsArZI2hUlJJ14PEiQX9oX1v0MxbKfjokPP4siYIxW3T1EQS7zb1XJfq/5syKbD0n3b71QUfYRuwFyR0sJNbAeNdmS56FrL'
    b'lB4KBsS78OKjru2+vXiuSaYj3b7sDBBHxe5570nJSdJNMVO8P7M+0FLGme9UXx7SFwa6Cy+LhtRsA6kgyW0HdU7DP6VzJdhp4ZXb'
    b'HcsH+N78SezldFkXK5Psq4HV0YxB87ixhZ32cEMwoYhxbC8sQ+pq1nkbFzOvb9XoS6WNPDvqRsIJgXk51U+8LFt6VmDCidZrtFHc'
    b'DX5bbeHEjfGHYJYvgkPoMoIRyCEANLL8S9uXIfK76x1c7PsXIDm/aAUba+CdegBz/eTcasPonvndr+sJZCjxIik7nwLtF0Bmp+gM'
    b'4ObZ+BoIHnfrB/IxLgjzOxvnIr9qxuYbXqW0fwPzTAiWHu5PsPHfTQJnBbBJ4u4KgXbI6yDzrLi1nhXufmXMM4cmbR/02kyK8wBU'
    b'65gi8NeYec8+vmibWsMOYtnGgTFZSPgjBqR5GkeqP8WgjQ2OhcVTK5ZAnBRchlXoNwX9NdrZvLkxzjdne+3gztz1ezyOPN/DyD/I'
    b'o8jQp6hHPkOJVwys5qdM3t7k0Rgb+d08Ss3ichxvUZ7oqMJFLWy4I7KDbE987q6vJ6xbhTAA4eOeEZ/pbfNDGIaknS9Xvq2d4W4s'
    b'5gCABZl3It4Y38Q8LHQGHLXMSu2dsX7QBrQNeF+4ngzxkUlBcjxw36Y+c/8Xv4psGfKytA8UIE2r8nQJY4iXk9lit4HxjGO1qSX0'
    b'UiApNOL88CJoERFdqXJxA2le5ot11YDJHMitc/eZYvhQfB9n4okPFdQVBHUmcPqdysPrLyKqIPBhiuaraFXd7rZr1Yx5LALv8QQU'
    b'D3qv6YBDV6q9U6okW8ZQYe71IqTweiYXJ/XkEqkYOTYH1ZYyCPbQnOd1jWRfUyD3FrlpqMuQ9q92+gnExmLDeZXEgqD8nogfEMQk'
    b'hjrPtqpegXcsjEl/Hccocuom9zzegHbWIhzyqVlHBIyxaVkpv72em6OemN2a9orm07phKw1czjCLtxb0BBp+rocYRKlBgsaQvIRR'
    b'rHhNNQ+ftsGUR1VU6RGzBgavBonSIrPwA7F5eLQIYWJtMGLxAM2hLaM4evE5LLR3dJvbcMzu29ZJCzimpcBu2COp2CGHlJ0+5rpQ'
    b'uBPOTW3qjOvCI718UrgEVPfQnEBgZqb7daAfG+y5ZM+CxwZysO9/1wG/2s626TNjAXpTx59De5UjVrBaPxhdhA6DEpAWMDd3Qlz4'
    b'DjnWBYdubPqPKebEro2rfNR4/uLs4OgSQlfFyo7OLrW3oz4cab9FQDHs0LEFxfHpMzXCzbq3jr4+bYmRReaCeFtskrBdqt+9+fJl'
    b'vvWuKRSG20srGdntkpLTM5JiF0sjTIOdCxtwx9wSATNmF6FUJy2wqKDu400B2SAejJITTUylO73FFHUgTYlmUtz1T1F94ZrM8vKB'
    b'W5MQlPollBu9+sx53JciA+EAx8kkUtNIB/Qg0TPAA25qxlPfWxRwhTnmhkTh8izy65otu8FOxlIHR5fZC/0u/ooa0s/iSPPUMuh7'
    b'Yhpu25i6X6im8VvSxfodHsqsx3V2kIlSr7fOMzs2sLxNUHRU9Mq+Sqz1REg/ickjd/uAMqU4FF1fO78xObRrmYZOcgouOkEecCcd'
    b'98JKKk73o2cSWUU3yCHzHd7jvMm2TxHhvVk6q/BLGKvkX8CaFqwcKa4PcxxarmSEU14Q9x5q2rrT0sqiu5xd19Vue/UQXogZ6tIE'
    b'aAhnH4491m02i+wrF93Rp5EVMScjYaloJeP8HuP48fA7rpHkvDx9jpyAAD9d82R6JSsAF510fRo6HYktHZv5vWbQAH+a/Q7CzRC1'
    b'6+RLTfYyy8sHHYnmTZ69yt4ssmWRX5dV0xYLCwZpMTWWO4iGua22O5DOluZWhqrx7K96L2HUnNmiuf1rtqzuSgijm28wMqaN4FmV'
    b'mAxtebBrVJ3dFuoOwndQvk/XgeaL7J0OyrXRyWUfMnVf6Me2T7Omwgg2oBDI6l15cKtqzOmJFjhNq7YYVasoIdlnm2FyMVVnqORF'
    b'GBME9FV2W60P6NoFRFfprHAQU6dWB/WuxACc0JaMlKNZnQ31bhcmiLziSjR3DL4wHsTKAq4aLYtWZSeXX0l+J6IG4XsOkw+jgZV1'
    b'G2+0rPM7WMv5lVpBxBw8EjhWC5CvMGK0X66HSGZskWoLSItatHO9Rqihx9BL/aCYomwQJCoUaJUF/NJCrNUtRBQWZW1dXF9DO8H8'
    b's4oYIBZrR7p+W61NqM14IXYM6W6+fbPgpbUCNY25Yc3XkDmGbiYiGpJYN09PAi9brly/HXLClbo+XmLUY7a6lj8IgqldL3gtETxA'
    b'W/vI4Fn25DxnLFwnf3f3Sa3dmhoud67/nWac0Zzb3kxigUob/Pf6Ae4KpKgBJ4Cz7M/5FjKtOy9gDPmAB44O7ZVfo7mVi50BpvyU'
    b'DtTgRPkJDDKZkrC5yeutStXEQqhiHc6Bcy/hERzCbMXqEICpw2qicIZiWaK1QHrjtfW5xMMDwXAYXekZMEeIXklq42h2BMGNEASi'
    b'Yh6+hVBHNHT8+zVePmwHDyiB+gt856URTcx6xaIpLG7yzZZUHJttXhdNVQ4JGCdxYFXF0vuK5MU6rBv/RmMfjUY/0lgpS7uIIuX6'
    b'A5Z8zVRbSejwajcqMz3PVkUNxwSi/BnCSsKtuJXYnHf8ZteA7h4sRiDl6NVDlmeQ0Cejyy8kqtYj5O1T5msCNhG5vz8/evV9/n0G'
    b'98FVvmgxOjfoszHldK2w39lGKTpFoc/qfrsuFkWbffP1v/z46s/5/bffZtcVKJUo4LpNjL3c4cvpARRShhE6EOzRbncZzgsdkqPR'
    b'qCdYnl4pP8SF/qzZCVAs5A1uWjhWxzHIqVjNSdJXHoNYEW7/jYsWPl7H16RTxC3TRy/4HB8T/nZh/g0U8n5QgJh2XiZH3ncAxGmK'
    b'0t47TBITHd4PArT2hAbSdvmaArQ8Os1ObAoTCrhGkoNRYXPZFcN7ccYJH4gfTjPD5bBVQ+GOZ4/kcccOsuT8szW4WFTryO3SK5XB'
    b'AXlhIiQfUISnfO/tlaWBhNa+ZxFkLZjTizBe5eUE/NZsF9MKy+G97VZ6kjX8QOD4NHdVSsdlPLKBaouy1VROPNvtunAwEdoEu9Sx'
    b'3R/u+vbP8nw0GCQdX/bDE5n3A+pdoAH9LY9DG86xjAGO48nn2X/yZhHfRXzDOQLCF50AF2lF2bakzmEGeh82tamBHDqqXYL4uX6Q'
    b'9/91vrla5nCGnQ0R9FzQE+8xOL8vmnMdCBZ+NPVo2tCiz6CYaawKJQQyJou6wAp4+2Cz7PDgcHZsEiPZ9WLwcBKzBHdyOQJKBTJn'
    b'/eX0qCsYCmSQWlxjDyKRpJSxsZDEo7O7uJ4W5bVMUY+4egYXpzdDQBc9tWNXEqI8bi9icSf2xKATjOX+8dO16VCL8h8Nn4y7au40'
    b'yCFSIceMVqJ5xqjKLMQnE6H/0Koa3gEx/hKQnDM8s09Zw8C9syxWCVyEXSUU19FWRQjyUuiTf+nUEWnJk8dhPstQVZhdwUO+jbus'
    b'dUwuRvv9dk0JzN1KaFQmyDuFfG9v8hKCK0PaGSWWgUgvb6s6y9e1ypcPmF7daKNAJ3ZwWzTF1VoB6E5BUpns4ghCL19+QVGer3d5'
    b'vQSlGqZzyqwTOkWNJsF7sVZ5SWpBF7P3vRfV+V5HdHZBZMnKwAsjG37zLWX6GJuHAGSXo2l2PM1OptnraXY6zT6DSK+Xk4n2VKDu'
    b'81dkbwjUfd5zBwyXBffHnn2NPM9id/2+IeGC3g9ENx6H17O+wO4En/bs1CDZbxrm57gknTx1UUebHRBp1ihjMMuSgRZ7KxLqdgjw'
    b'urp2nHY1ov13quRxnuGtx2pbG02U5+8ZTX9w0e4aU2A/fAB10lLZAvzjwySbzWZ0G3WXFtogIAc73NJgzmB1QI7XCakCgDGBiQUk'
    b'3iaA4OcKXEgGRcj3fwx1RAs1a084YeMM9kWkSQriWNN8S1T2Yk8CzSVMh0OvDoqkN79qjfUbPCvE5+Aq4RveOTfy1n0+zFKZKmKO'
    b'c6q1Ku7V0k5NooaOhQVrez5a7dpdrTMkipXurlxX6306GV5qeld6+GI9iS6iK526dfgqoLhUH0VptdVRAPDov2pnnoo5FuUUoeO3'
    b'xNAKz6uUuNXHI69u9jPNFFUFczYD34RtgIHqVTszDDo13pvHjPdmz/HePH683gFjBnzjqw+lWbv/Kp9QmQWauvil4HEXA3Yd6L8S'
    b'8LyhvXkY1g8iwZwkCS/BHFbVSYYZVFJBauZbtOAtQqoJDyzZhr6GWdWt7trUIjB5ZHbF2t4lBbEYwCGXHl0f+xS7+ezzctB/I/Gk'
    b'qr5bCNxjeQfjGm8OsYeme5jGCByEP0beEt1pDGAcyw/izCWWXSHJLRpfJ7bH6DTVXRcQbo1lP4TMQX6ZlxTQS0fnQ4eJcI5cAHoG'
    b'B2Gd6nxBBhPjCC0mXqT0WIk2knnXqdxL5MTpieOK8XujD4bcTlF9elrXCD/WbF3fWX1dL+afjB0zCdKBH7cOFqnkyIjUP4aMfng0'
    b'mgTmQDqRI/6OKfy84zCm1ZdzIsDNxtNpy0Yjk7EME2TxdGUjOi/Y4NiCGAJKjDIykXspzIMRdjwKDB+sDsqXHDAqPN+8jo7YpQtD'
    b'5a9oxiMkeBKLbFs5qH8OSMWr1hUH/5/9BfDqRu2x4cdyIy6HkGHEr/OSaZq0cddH5tl3FHZpr4d2rG00EUke5vB7+mFXkBC3MCta'
    b'NEEa0DamJxtdZq/8cL1WzLLdBUszJzGypgHrDM3FgmiAbR1LtfCkuRKYeudtu5yB4m++aG7HvL+RaAfhl2DRQeYWWOSuvV+obZt9'
    b'h/8UVdkz8giVfZr9sFoViyJfZ1d1BTZ06rZYqnKhQIvlBglqSlBnQbABtB8MVKRmFmZkEwEJjsG8jtSrlLEZM3SrvF7cAHfY7lp8'
    b'I0D7CBTib6pKOzh8muXZslitFLiIZ9+/go39yupq0BItq64aVd8a671aoTQJiBfVRifoNgrSCI+JKKoloCwTanAJ6LEQhLwCkcY5'
    b'ALItkwzZ728rHblfCzcm8/CeKUqWkQwlQbblfgnrk6e6ho9skmwSDM6yQw8gIj2kHdsf4dQO9nbVZqPKZVQLHI8C4OPYVGUBJjsQ'
    b'00uBbesc3FF1pT4ri3jdafaZ/4DJb6IiRLrkDkHntG4NnyBGZ/r66S2dM/NIgH2Ik9vjc16L23AyCSGXY13+m4GZcbB/g9LjGGBn'
    b'9c1GmLA0h9b02/T9GeucjQsK7yzkCuQnlYxM40WkCzooibgA9a2Ai7Q1ML24N35Iu2v8K3RW4aMpetIZGIiec+RX20fN4490kCMr'
    b'W4xBais2okEb3PeC9bEktqmp9oRN7jWUEH6kcxSz/eRHSrex6rCWjBZrYFvWvHWvRszL+bBGnD3sXo1IJfOAduJ2aF6rgp0a92fL'
    b'JrmxzRMWCX5ABhqOLr4Oe+NJTDX935pXmGHHpjBqjiFTTja7zSavQZnpJIh9pYdRf3wdq0GKx9VxxbF4OqFkYvxnLR9kB+1wMWVP'
    b'EeWp4smvIJp4pGzi1TyO+jlaIulh+ALy51NAND0IUUj/DFGUP5w9B2eJNzJMyAsEPDLf4x8jlCrW6hH2biFGb5ofZ/UWokX+oQdl'
    b'GQqHW6vrHB5rWbSDM7PNyL1nbq6X86Xa1mrhPcWOKn3VNThqcDCpMYbTiG6/87VagkcQBqLB+Da8fr/0HIC4ZDdSnzByPZyLIdjY'
    b'DdjFLzLTZ2aj767oeHWG6262qqtNJl/XzJBqtV3nD6/4qrwyRPs38DYAY6UFBZxQIF2iA90rb7II1rXAV6baKvAFKa/nZQX2P2fM'
    b'XQ4BftTrcoDegeaNiyl6sm8rvATvGnQ4gHyB+vKcN1nOx/7T7//wF7SpmvlXTKvIYOF2rPPF33bLa4hj9aDVHAe00BlNDvl4wKIf'
    b'UMgmEOThGaxsFUAB24FnMfDmmuJBC4FgmqALP+5K49xhebgdLo6dfB1lJ17p2c/c7Gf5uqky2AEqaGWFzTienS1u1OJdk6lbVT9k'
    b'76P8/rcD+P1vkd9/yOD3YGT/2ki7OPeOiAvUqG0O37WJA5EjDBTUPs4+I0D79Xpd3WXFZqOWBVSn7sAsQbgUDIybNdvincIwqeiS'
    b'B48fzW4LOLNVXqxFX/UzK11itTbDXRC1PPLJJ5/Mf/rTd9/9n9/N//LDn/7wzb/Pv/n6+2//8O3XP3/3E7OdQsMmRPR+5FKxwVMR'
    b'rORoysehk/EczQ4hfwXZhVAGC/gbDUT0nx+mPsqlWs3fHM6PT+dHpw6rQXk4e+OhPD4VKI9OQ5RX+Xp+ejg/OZwfH8ZQnnoowUmE'
    b'oTyO9PK6ru7am/nrQ/jPYnUoX3soXw9GeXw6f306PwlR4kA5SjnwkwjK/Pq6np8AtvmJm0yH8uS0c+AnpwmUx6eA9bWbzHQvsQmH'
    b'8nWql0c4k6cxlEfdc3kKKC/1G/q1KoH5qnlezFfVrjbZ+rRpk7PKHKde0fFlMmYx2Pe2zUxGuYM0H2gxB1KkFT4+RW/YQ1iXwYuM'
    b'xZj/ELePWZ9EO4fz12/nx59F2/Hn9K1s57OB7WiiPXoDG+z481hTR29kU7jbWFOf79nUa9zLx9TUa9nU686mTo5FU697mzqcn76e'
    b'nxxFR+VN4Olr2dTR4IWqr9R6PT86nr9+PT+Jz+Cxt1heW5/v2dbh2/nrz+cnb2NtHb712vpctvV2YFtkBQgtvQZqx5ZOuluSo0LK'
    b'dy2dJFu6qdr54Rtcqc+i7fj0583eZwPbqRVlb4OVemPb6lmpN11tpWcP45AdvZ6/Pp4fv8GGjt52UvrrY7mp3vCGjt72NIS0d/wa'
    b'G8LDbDDtHb/mDdljTVtW5/fckJ5iMcUv4B67ljVHpIl1HyYTjOPExRpXeHEma5ujwd4kxYkAcRPh9WqjnuhREnUicdKTdAlhARpg'
    b'rPrySD7oxwMdQC6dE/euzFS+uDHiJg3N9SjLr+G5sc1++OEnF7sWHZJAhIRnyN26bTCICdwJINKGgoAgMC3asZscxZtsDA+YGKwA'
    b'r/tu+uBlnJ4ZD/CRc75cneEbKZg7g7fJWM84kh+9GG90jLMJ3TjAKXua/YRKjamOF6DN5RpCnWVfg2NKW6NjHNXiiM5/+/Wf/vTb'
    b'bAHxJDEMC90+XLxezEpguhmOQPaYPkPCqDvzrnpTXN+opj2gTuqZHur9DU/2wq9EJswTWyUpkn8Sc2xgXgfonQxrC5b5jiZtK+sr'
    b'eLBF1Upe6vQRxBGmLnEx06NC/EMgVxl6wdXFze+FhsCtAsEavKdSkaSToaDnssPZZ0GIc8d6/Eq6AKodh9UMh/Jr0XeodCQquQDS'
    b'FKKkzhfxsEzldrZYF9vQHMLOEzxgM72z+a7VrcACMa0fBI87gDvYuKlsNoFYhHeADj4e+R+jxlYrNpqvAJG0iGgqikpL1ugG0oK4'
    b'iK8eu9Kc3MytKJtMHSbXE3CFWY2syX/Ae8/0Tjp/v75afyAMm/z+/H2yD2ez4998QCcXZpfnG7tI55MOf5OkP0XSz0SPxASuPW+q'
    b'EMbr8nlyMKml9A1aQLug7hdykP1za9kfKAjUElkETvRZ9l7dLz54ZnNBTs5NHfUp4HS2qbWZRlWLeEzG0nJTpwIX6LbsVziqDUMG'
    b'vxjkTagLhjOjndPhS4Z5OkI0fOMGzFRoTlw8TIFJypY3HZGom8SjsW0vUY7+wgQRer3JTCTOESiSVYOflKMzYNmRyPmoe4FtBppy'
    b'2MlkaxACar8cBqp5ZwyY5HYGSxwzBmr3+ejM7fkUnCP20Vmas0Rq8+Md5gKlhxDMvgiZWJ/RZBVa/b+JhdeMgNu3GF3B+kB3VKkg'
    b'OmnF6ugPXZXsG4KuY58H0lUgmlZelq6O+dBVqWCDL5JDl9k20YdJL4KmS/nCbNy44iChk5IW2Ovqzm162jQQ7eQ829RBHHkw5BWf'
    b'JEtx++uTmJsU5yajr//0p9EU24iEmsfIX9J6XJBfFyfDfAMIPM2u660GZYEWGZ54xiOg3Ot6O8m+zE7imY6i2ZLd/EGz59D4sAm8'
    b'rrcdM9g3k5iIDP+c4IDjEwrj0UbD+lLQ6bykYRKGePbqEbHcdNgNDmmgJeZ/miUpmjs0cbMt4O+eD1M6kgEtSUMmsGkx3SMX0/Fe'
    b'mjE2GLCA0GyZj5vdVaPa846dKsg6GmAlSmF2GIYGwmgSF3tPpjeNgRGoCfsGdgoBwdgeTfwcKHy2Ok9ojaDPY0tedZcrT5Hg6Sxs'
    b'tHJ4i10/T3wKnabJCHBMzJFxBp8UO8L34pomW9lPB76XLt6FODcGwJG7a8Igt+/v9x8oD5xeWyQTc8XgoezxYhfqpuQBxwwVDA7K'
    b'73lMdo/mQsq5kqUgZvzcrYZi0+wO5+Ay4ubo3P3Ki+X9wxu6jscS5b34vkh9HmgV7Q+VTTsRuzEsIkNWcna0c1ouMQED2LEZDeCW'
    b'drpxuLDba7G6hmlcVyX+Pgcl0Hy39fLzBJPnqSI6WwbRl3XXN94W9IChm6zHxOgM4/0wxQKfZTuG1MWUD3Jq17tvITW7zBu1LkqN'
    b'3OMcsMDBJ/+GEumQsyumvpj0WgPiapgQEWuj8btqCRV9pBGaWdYjAtooSvZ6BrnoKTHe8qHMN8ViboY5mvIRT50ryvsPTJ4d+5pl'
    b'M8NgKexWg/0h+7XJTaoxzfv06EPdFhsqCNls4J4OzGxUkX7N12+TC7PFAZ6hyZHoANuBgb+Z0XlT/F1FLPnYpOvIKZHV8HGzVJHV'
    b'3Yy23diPZRFZaT8ohV7O0VREnWBD5ipI15L1uXbWF2BcZC7v1LCNAiBxdIRi0FO6yLfhBUZMa+Sy7tsBJqLndt3LvIQGDEcqx0Ps'
    b'5s5SHTAM/POgu64fw3fYbdfV2ue+68f+7aoUTdTFUETL+xDKVJwCFy/q7ZcXkd7vllfch+7mpvBRwKfUfV3+GZx8QvIfylQ8f2jY'
    b'PRH2MEcrONhB8MtsudtsIznywk0DPyahbbyUvxdgwjGTjdd7MgAtfvY6EcpFviBE0LBHhH5E5k0hgsc9K/Sj0a+lsUFByTAknoYQ'
    b'5lIjESXTbDSaoE52lMAmlT3mh2cUjiy7yS0c1PVIEX5U2YD2MW8WRUEuORFlOtzjIBk0XtJS2vBo6BvG0hO6BXlLTIQ12cdrSMTz'
    b'0C3H5F8hQnJpw7tHWrHrriiX1d0c8wc98f6IOOYgoPXHKEzEYhh4y3Mt2dxH+i9fvNQIZ/542URidWoDg4qZJE4mHh4FwnPh52To'
    b'Pl361Xl2pKPXob8YzRL3Jnvm0B8Y0COiifHSuD4qoEcQW0T4eiQDjVA9SjE3vGZhMzvNy7zEHQnyfBjzJxBLPDGDRQu18kDIaFgs'
    b'bNRGh3H8wTIkfqxHjugwicxedxWiNRvPDv/ki/PLTjXkaJXXMJ3OkyY70IumflitGtWOsS6GC6PkYJPJrIR3pnXxdx5HhEglGQ3m'
    b'q3O/VeESCT82DIveIIQxsrSaOCczk/xo1lYwJTyTF5hK6D1p81tykmHUNMm+9OjJ6yl3xFq0u3xtp03Uov5DFG8bs8lp5b7Pf+a8'
    b'nxihW77wCsb5p77v0PwHVyPR16QnlT8m40/loeMDTOLiQHHHLAGRynUOub728Pzye3qbF2s4AaQDlUmRp4N+QCq7aRbaVOgOerOs'
    b'09bl92OxIfzxPjSAMnuVnbw5nR2f9g49sHpgnadDBo180Fsl0QVOr5EexO60+hXGTMSX2XEgB5ub6HvXIev4AsKm3UNzXs6+p6W6'
    b'Fy/evzvTMj6JYJjBxrDiiHBlJydILHk2NK0khnTL2x2s5agomx36jYDGRdOIPkrD5F3wk1JkOb0RcqTg3TutObCaHC9CSHLq6WXm'
    b'aTPPpqCilLCcGVIi2C0EnLH0z6clKpjGTvOIPCp2U09sbHLBgseLwCNynIPrCAu/0ZxlQtybmmBDBgC3Pop+RalNIzQOL/6wiZ18'
    b'xOSuoDWxne9N8GCtytfQgaRjeI/XM5c3VScqO++H5BiL0szGNHunHs5dtIIxJOXRUuKBxj6x4ZVtnh5HP7EAySSZW1fU3uQ7Vo63'
    b'ABGBXsMt1Srfrb1F0hI6SjCwlB3iOZp8ra7jxid8jc8cOicFsVDSZlgCE7pUoz2PBNJPBlDcE28rqBk8pTsalE5ztEbik6VGGTTM'
    b'b2PflBtWVDISkuyHuGbYossIvZNnnF4mNo/Rwfo3m/AZKjIKdnPSA5pmFyRLsU7G+pbsA+wynwpxm10KJzItbqrWbDW7eYoSciBE'
    b'OkuKif1DWHbtKw25hns1pseb52tVtygbQSwOk81Z3z4iTHLQ5VgKnn3X44CNJt6gJHONk3aoTEOaDAYSqmLgwSfk0o4KQ0UN8AnE'
    b'/iTaq+rswtz0kxuPWSPAT7DF2FHiSWmTfYl50GDsCI4oa/flJ7yZRAqQSHpynTreZv1wPbNH2YBDnE6kfTvOHztol3rXI+/wlHcA'
    b'cxhGH5FsFes6QtHBNaMY9dSyTt+jr/WUMX9g7axQNNmyaHD2vjB+z2CNsiqudxBwTTdlT5DAd9aYJoFDC6l8yMkmDqY9vOKAOshY'
    b'R7Ba/jk8bGM5yVCuQL/ecl7VZubGi8rYtuovwhXET9UoNUew1ViCsGVnKFO6I+lGHKVQ+DZm2C/P0mUiLdiMRsK1B7F2rC18mZdg'
    b'OKTvdhhniPg3bB/9GIH32QRDRxW2ZeaWB4xh6IkqlHEHIfR80ZeRD8hs+yJTiIUmHt7yIlWbaVhEsKxqyRU+mp84nDETrMicWHBt'
    b'KaUf/CGwIqjKyE3lPEZfI/LlmUtYG6EMXCRNVKFFC1lZ4ZKzKLbkdt+JMlYDUZ6capQPTas2xSKBxhTPF3XRFA3rk+7SIq/rh/mu'
    b'hCtSAgcHgQhIoIIM8Nzl9bwq1qBSTM0SB5k3N6BCDNDYzDPzumq75icEDJFp/qN9ChOIJFASybr4ZVcsId11JxoLlkboQIrNdgdb'
    b'NY4xgOtCtawh6EEfIoSKobHbDaMfpNAIqE40PVQZgexEd5fX/ZgkeXVgc9mNenE6KutCSGvfj62L1ASzoU2mPYC0udspeDJJDkMd'
    b'EbwhWvXkLThBRTiJvta701zXc8pzvTrc3M0xA/eVz737Gu5RV+YRJS8QZBYtCLsl6SD63fbGlcr5dt9jU8pNzIRg48+ZXGWH1OcQ'
    b'sbnQOz3af6rviuwCe0cUJEc+PdRCpkxEyILJJjyEQ2lbd5vLwPpWSIenlRjsu5G+w4I4CuW/g4xMC/hf0djANLVa1aq5AQfGtcoh'
    b'z9lNsYVsx+W1ajLQiSzyLZgNLLNduQaKpoC7OEJ4O6rXD1leX0N4c7jH5VmD4dezxcNirXRSJiRsLUAU72C7v3cHIn7HDFecb9iv'
    b'WLdarfSXD1YakktDswBp0mVbFgos0Nn++iqduDEy91izvYGZqtZw4YHILEwcrOps7J8BX4FQe3pqPY8ZZXyJMSh01D3/1vQo4oAO'
    b'wiRZ6njDemcpxM4lrJEL5+RI5MeieXdQrVYwIDueAxoP9f0LcEhW5dLEXdb3GtvntspqtdwtVGaeMXEC1qplyewol1mDNgFgGKLJ'
    b'RK3FunrLBaIWn/DofEuQyLSfvuUAUTkQV+dQNhU5s7C916fPuIhyA+s0zOEqWrBfdnndKrDFiSzl72jshu7x2QKkdtz8cJ/9Ancq'
    b'3TxzCinWVpnFme3Ktlgb73g5Q8VmW1e3EJ0qtm6SKe+30XTdjq2G1OTJSV8mm/BlJYn49DRALGnqy+de4hQTFwusgVZ508ZW9l+w'
    b'+JUThGt1QIK12aKgUYDaqg74fFsZhs75vRELZiOd8uCmalQ530+N402LeKpgMUA7FTOiYRkiM66bsVfGLmCrkiE3LvgjAi6VKURR'
    b'7Fukhq9X0VTIv+paH4wVFIa5n18l5jLx2BJaPEWfTiBBzXCdsgjRsadquf+F55Eq5cFPOkCU3Q9X/jQyo3l/9gypMr8u3NQDdPt8'
    b'JNR3/wFEx/Ifgf3+fIlOqRVGDF3cLcGVZJi6+cwMnL2Li8xR/ld/Kc8T313FQIF+brY2k7jjvE9MHVlmJrY5RjqJv7lMup7lcCZZ'
    b'zk75Ghc8tgb+L91BdX3WJdWoL16I8QWqUwinjhQZefDjNnDGWtVmH6KKoRqO9M0WLf1yof8RWGS0evXL2M9kOQmsqLRajrcRTT5l'
    b'WueAbLgXIzvacrdhJoVGm6pRIzGk53+SsDJMDV42qt9N5CCLlZnY/1ra6JyrxHj0aoKxAtGWjlbbbBUmE+G+QmRFWNRzeHjjFs++'
    b'G4T5M4QLTB3h3wicM13c5PfLpYDQT6V5+Q4cyo3xIeT49ryjaCSLaj0lE2jQ5oPfOBshWyuaHwPYSV4Oc4SaTF6GA1DNl9q9jvcY'
    b'SHz03jT0ASmdiV2O/Ew//K7N4MPYs6mewrhuquX5aKnKhufqsjNljWj0B/N2UlACqflWlfka9Zx7CNB+bYo0dErWd8nTCUAEvZoY'
    b'URobkuw4QcwH0W0ymYH5Cd/MFyMegQRH3cjdYKfmcgahgvL7ojk3gc8k87MZLHpQvwyn80V6kDHOE88aKjviPOwtLrYzvQ0odpnc'
    b'UVBJzC07nH3n/NBF3/8HIDQG48iY34F3jhtb4ItOZ3y1jZmfEkdDSz31MKUU9nSKIVbjJiEe71g+NIRHpx50lS4WfvKuanvxTmFT'
    b'CIr4xl3meH4NKT1T/3y24dLcXUCfKTgIn3NMmtR7ak0uY6xGT6c5hWCP8eBYsmt8ovw+04aPXqhg0F02Psx+TKLFIFwThiQhodk8'
    b'K4nWjV2iOPfEZa+ttiLJKwZUr3fl3OY5wMvmHsYx0sL7DEiy/95CEDy3gjdUbW8GUFsIPl3twJnDuql7NxxpSv9oexnPu4H7YEQH'
    b'm5CPwtykxsCmY8DO9MaO1952YjPg7eAYCIVT0E/dmkUA3LxZ3IDNRGSYXtu015BGsM5uLbJgoPl3SkrEltw1P78L9rt7SrAbX/AQ'
    b'aXcXmRrsXgBkTMTl4RtcdqL1BjewR26QtLFvdLa7bGsCmomi7s0IT1zQA/UWUR9Ogm+KJWXMLFhqzc/8CIQBnKZNnjtFJPx8ilXG'
    b'c75pmGj8sGOstkNLGUs8FeBAp2aJ8LxZio7ObSlETKxYbK75qqqdBsqyp4AQzqP4ga2bXMpoRd60ans0z9FCQW2PR7bDpLy0bXuv'
    b'U5TYAEO3ZlWJWmnoK6Y04K1+OMB/2dMDjMHoLYUeerghGyiE56jvhpm29mxCNWyN9AR3S8A43xS/POa/kn0pSyItMGFBkASKeq6N'
    b'KF0Eu0eqnT0K6euJv+hs7iLs212kHAmg+j3Ua0seuBp9ByleIRLte29YhgRgg9IzI1xomrZYr/UMfOFnQ3mn1JZeOii+hgvQoJ85'
    b'oMx2PyQux+IMmclHR8cHuLYB97PVofOJnbXVMn8YC0e57KUBWap1m4/Bhwe96ox9KTXCknYIezTHPHCPlw+Nmrd1DlcGAJ6DC3A9'
    b'x+ypY9E1ij1scudAo0faskIP1eGOmnX7BIHbHtNk6L7KteCsAPECq0CSMCIzI3DyRTHdvVFljLI6qIgo6U9AKMTDiyZ775buwxfZ'
    b'sspybalfbLKfWrXNjk0mkqaqSlVPPWJCgoK+wKhd1OVtscXwLJKHDaApoisahDvqcSXZzCeWgWaIb+HEq8tjUoyFEkC/yEMYvB3L'
    b'MZh7szuDdui/hQ6YduV5De/MIgLSjzn0B4eGB9oaUvN29VFSSfLwZJtg7FEmxZwO62X/dB6dAYkwDEAYDDgpC0dcIfn6x90tBUQ0'
    b'FZ7eAo6/pLxENRXG23HF0UY4FdpbYbopvh1S7QmY4Y3qFGLm1z5w+4JIv8hHPbrl6vNceAXGb7buVsuvw15kg3ScgsilEjOt+1nX'
    b'+X3TGXd7jXqKcwJKKM6pkGEdElggBZm40fHrcaoqOf0n7+1Qs8qX81jZGGfHrsDSPosZ8QYlnrs4CvK9b4bhYLGbIL0XcQUndO02'
    b'4yMReIQaNko0DFCFIWNmu+1W1WNkLN98/dPv53/58Yd/+/f5z3/45o/f/Silzluy+dZRViYmtbCWICNdg2huBeo6if1G+v1Vdhil'
    b'o4s0BVhSW0oXfgwwm5fvQCJR6+K6AJdVGLomuog1eqJJH8mlUfJTOBPRqlQbWpT5cjmnmNK7cplvVNkCDy/KYrPbzFfr/LrRlIvP'
    b'xpPePiVxYWrDrg4O3HXurkqSjAkqGJjot/AiDvt/SmyB3XIJoMk32zWIau6b9NLVlk6oeKG7+cHRpacLcnVlBEoiQbT7d9hZTnt7'
    b'6GGxtnI+nB26b8xkWXwn22PxiRsQiwJrCCy+BhZU+nL6vIaJ4UxHxWY+fhuTE5zfSXnFU40GGHUei6gdOARTKvPyHOMqydbYzD65'
    b'Rc9cvKNVWrcnNxixKu9olFPGk5v2jc872rWE9+RGozbqHS0LDVYvdu7NM+VqLZ/TpX2ADAPBP7tqMeK0leBbVx2PvGw9872rboRS'
    b'bP27vO6q6q+0rWcLumpHl8yioNJP9tKQM8nlH1ZN7vfx4+jKB7XyvArzYPK7tOaL1XXaAfi/VIfuXoieU5UOeDrH7JSMjlxRV0iU'
    b'YGROOyymqN1HSSv1qzHp9h9Ii2swMIat3Vk9hwWnZ4xOHlMG10VV2yEnnvGIeg0QhUjUT3XwY947qurdDmwDrDguzMYE1MWoLRbv'
    b'VE3cLV4iLNOatjYXmZ529d/oYTpf7rbrAhJlNy7SnMEP4U7U9ny0KuqmHU1mLpSMAZlmGFSGZG7bLM4jC5MmUuhoeyWbswBMGxDZ'
    b'FH+nGyBd1/jEh7YP8EM1QSNrtLwaGabJol/lhtf4hY+yazdQSgHx6EaqGqgPfI/HGhg+EQbz4ctzuhCG6TaiqTYgXbUeQeTqGSKh'
    b'QNGJA8T8dMQ/1at2FrbVEcro+3yDqeC/wWiiaTjy9BgCGajb3JPYwJiivq7PTaS97BoqR4JNTaUEBf5OaByNmh95N6urO+9SFk+w'
    b'Qq1AqCl+eMQhPG4QN8h5VirQ+6536Xvh7NKTNP4rLj0GEtYRG4G7iO0YQtoQqvAia/WIWNM+/YoKN2q9nEO6dVRUsbcRqHI4O+zZ'
    b'wnSaH+krssBM2qghPbfsNIgJZkvdY5sXsdbWDayTZT0eckl3CraSBxQNCCFhxGpICTgFmLYotR7I5qetQPFjeTjNWQovWjh6zwKw'
    b'XBzHV1mEV3eMKFn0SuAdMtndsxhR+9qt0llxHxL362qDNIrADTJoWtaxoHgKWplX6jYx6mPk+IXA+F6YkGRDrga/OsMPy2IxFBmr'
    b'4mOLryy2629P+CgfSfh33PI6l+XqekYBZDUAvANDyldIN3Bb0MtaZy94h1032FfZD1HAOhLeLeN303RX8HBM8nUPlijEiIjupFqC'
    b'uHpOcbLBfDkuvoKTRcBJu4KXm4i9UYhIpsHkHY//CCZErETAdK9b9J6EKxh5B9DF+2CkXB98m3pl3ciCt17ANJI3oVEnhl5tg+hb'
    b'59tvwMFiypcd8UBpjROr3a2/weQc/jOovEeaV9COVuB1A9P02NQ9Ef8yPCq9w8l76ohi9vaSjO5pYlPvE18+3tKsKBtVt+NDULST'
    b'iX25neU1hCUYH1GGdFkD7Ge4WRN7QZGA2sN1dY2fILnS6ho/rarFrpmDEYkJrAkcErNZkNca/LkpSqxHQbenntqCUNjTh9RCiAED'
    b'bkIrjYJAvqQUBU97TjUbzBIVK2EaxDnaubiipq2r8tppnl0JZH+D/UyMvi4W2qjRRrDN18V1Ce9V7ILgPXDJFTaRUoIFTj64waMf'
    b'HfoQwQNDnNUbHibIaEBSj4CiT+BXt2vBf9ZE+4Ug6vAWSDMP8QbW+UP4dIeejPzEtbmMQWliZ2nX9OJ2D1xSf9U/yVqzo2elo0f8'
    b'CZBSX7VrNnhreG9yDMHtva7W+OhvnqX9px8ejcZq4KdSqa7/vMuZViIk1zFH+JWJb/PmlIg96XCfvYQbydsJSmTyTHejvKBXtc1u'
    b'3RZw6oCC6avsaHZ87PRmruXD2Ym7urgu+7vIHwK0H5sGq+PHQKKdg3nUIA7fxgdx7GJWRF+TaMNTd/UuD/vnB07QAeHcK+OXPSNy'
    b'K+7xE68ndgiuK4ezz9j66NZELA7HWqET9JcJWWK4JeXkkktlMmnoKgaUbzrDxbVJTN6gIxNsfHGp9DD72WxN94Dr678kzzcJ2Tjv'
    b'7xjLQXbM2kcVkCDLZ2g/e5kdd/ZBnofYB7G2XX3wTj5T+DJ7M82Og6FJEnkU3pNpdnQaxeuyN9lXymQLDuXUb+7oLcNu6IYK9Ynv'
    b'zuoQTh77mo7lR1vJLNVqXVW1xq17BYG4x6+TlD4+tgYEbsNhCQ8EIzoVoQuaaXkZFeOV1wnjN5SmtMlUjonddobvMduFviuno5Rh'
    b'8JiCVAdh7G+srOZtu+ltg8AwJNzb/VAbGQfNqoY04ipAc9z2uo9tfNQpPTn8aFPKx/hrTOnr4Vxw3ynVLHr4tEJAOBaI9GPM7ptf'
    b'dXaPj/c4DD769L4+/ejT+/rXnV7BD/wHl4/KAV4fPoK7Q1JRjHRj1eCiXa+4k3cDLMWo6kAmAHg83ig6uGLdqBwU0GmUARAue+oY'
    b'wE7k19fdveQAiO70EWw+Prdij0Tm94Q4zsnrPac5wBtM9WtKAm4iGe414wH26KwfUwvHbx7BwR83W6/fEgM5ffbZ+oxY09vDjzZb'
    b'J9T314/iyI+crtfd/Pbx0/WGBvPZ6cebLur7ydtBHPaR80Ob7/Xzb743tDXevPl480MtnLx5BiG/7/xBSfvNM4i+gxp6+wwC4RAJ'
    b'RcsLvlT2eDFpcKO0dFLyHSw8PGFoxirWKScbpZaWvmxUIm2g0FfPmdDK+6x8IDSVNfQeL/agkzx+m73INKp5g0+BPG64USWPmvwa'
    b'sthvtlVTxAKbc5xHx3vgvO7BdTgMl5s6yvMMqdtKVc8Vup51t3H4dt82MPAzIN21nS0wtYXJXmtVNVLpkr0AfZZQlrzMjthZ1vUy'
    b'kaAcmGJDFCyCEo+TdDmZ3ah8OWbds88ZLpcJw36Tb9VYR9YMHPba3ZaSKk3pbVuHg4EfSLOHiVVsOhPzCG2eQEzelXReE4wi73YN'
    b'1QeND1bdw/ZSJ441oX4Iz6xUkadt31CFpaG1T/5yP9I4nL1ak3gzt2/jPVvW74FJy0VjmPIeafN696I5x0BsuXWX0tpR56UZqNX8'
    b'SJosGj0aRZ1rF0GwbIh600V8UOk91kTE5onB9aNgZCgQ4dQnO/faidX08YGVyGjFu3lYZMSywzhyOGDK0m6mxiLd0l4+MS+XNu70'
    b'87bH0OoWT02LTgB43iY5Xmrz6NC1WdKrnFGmnqTVtaeYx1c8N1HBESpy5UuKLjlMqXjf2h7k99QD6LI4+rqHLq/SYaeFKOAdqOFM'
    b'i2J/mKKQ0Pm0mBg/DCEgJFz115PUzATwjBdMBr+q0oOYZ+aGQeA1L/zSX3vIOMX241feyrwEa+o37Om8VuD2Izy03XMULppkYgS8'
    b'hxrf1enQ4/chnky9cUbV+Q6LR2e6X8nyqZylwLKz8/7AsQbXrfxetBq5i6YISOqywoaCG1jQVOR6mm7szXFXY9FLWdBg4saabvSE'
    b'NUqo7EOgv2LsAU5SghS/AmKVxyp9G3i4immQdOufsk87abtPW/NjpsZyh3M5ZekdYU9qPZru89qbNx/ZlWohRr9vOIbBXlhj2VeG'
    b'R8V2i0UiDGjxjulhOfcZHHLE2BqxUeH14PAU7AeYmMXrgClEP5/ExkL0Ai1j63uO1GfrxkbHW4BooOsO3HYOqVhW5GZxXjuSMdMW'
    b'cfslegu3EMYczfwkZMM+chx6IkZ4MqXy7V1RHq98vR567hnY9LFnIZBPhRXjB1KqOHkesQqxoyZVjCfNm46ThulcBI7YIZMGQN1n'
    b'0hwA1aPxZlLHSzcQKfo6Thc2qkCyMxlyUhYgpuWYnon3LKFjkuOUhxB+2uMMMm39Ix5BePYK2o9KZghi9z1V6D6F5LyJhZSzQ5Ds'
    b'vDC/YlgZv6XoySAlH3BB9Kt9eR7lJsGRkmLpcjQ62Wnq4OA8WlaMsWhLTSkObZbHMNfkwaJVFLI13pmlWu62CsIzkFIxLx/QE8oN'
    b'e5qh6gpstc+NosTec7gblOtEoDoa4vgUgRmoQY36O0XQ+fqbXjenRLeHOTbt46a0p2dSlzMSkI3nfERm6m7j6Snoc+NxmFgxZa+J'
    b'quJDtHG/HIeXl5O+NkDxeBeRp3qF9DqCYJhZLw7kc/l+9DD6PaIeDHQZCWlrD/cNxitcKDjubPmMfhp7uWY4mmdWqAFPpOh5FE5+'
    b'Xm1VjX4B+Rrili4gwheLEB+GhsfgVjxPwV/y9kb7U7XV9uSQo4zl0HLHZA8gzApGRx2E1kIPxp8vFmpLSSoWN2rxTowKYsoTmPEo'
    b'OMt+p3/7UTW7tZZbEinF4qgSEflDYC/APWR1IVZdbRtIZgVEButwMaq2jU6ggb6Om3fLoh5rKFr/pVoUDTh+QI3s3KJ4xd+VLNBN'
    b'0bRV/TDb5vUvO6UT4dld2YXCAkVRePEPI5holSVcChdGdVh2dscBuRQlDo0mAGRZ0a3LiUe/SwnJg5eLyLBGXopjYiHZugmWu/bo'
    b'fuIE4V3P2w6sf0FZtG8hhli/Uu14u/gdZU4fMcDRM0/VyPYJ4huP+hI68PkaEgGTAlvacLO8OneB9xBh/BgOqo8H7WO7Xc6+z3+2'
    b'EqsOEsLi1pjR+1Q4rMkO6bN/ZjpktdTs0MbblfPWeEiCNK3xznbtoqzuxpNZ0VS42eBxc6MgudQ5BIKoymUz4g+7GD1Gvlx6LDqj'
    b'cVFKEZM6UOd6hNguGFQC+SR+Ch98efo67wWYUA9//yVBTvfBCdR0sAeSPT0KE77YfMIJD9nT/FuLDiCKSE1oEAoOVbW6Lb4pvE65'
    b'uUWb1sfPLMil/5+dVqTlPSfVXlFApU9WAPLmb2wDmOafPriLhKXYT8IgBaZ6Kkis01LHI9xSbV9o1z7NCZGDhbULpH2eG9MEROiT'
    b'7v1Au13NfvKUCHUJeas/Upz0GO6CPJoECiBtLhC/UJjLWedUR+Ovi4wXNvaajdTmFt6WaXnIzTotvr6z5It2Z2/lUPqeAuSahN8Y'
    b'4OdwBlcIYaxkvzLzIvr2gaO3GwEpL4k/hj3ELTDrnQPI2IaQhYQzWYzoWanugvYPBcfP8lrEpqX+pMs1eplWOyjm2dJdoeYv8aP9'
    b'LGJIFEA+LVqGbUHwro9gcxT0++OZHzHuCgPxRAi/I1Ob8RoYmmboXgBXwZ778Qm1kMGo5RA5ZS6Bdy9SqRPi/XTaxK7g4XHCiauR'
    b'QjoCFBM761oboWkKy2Z5+cAXIR1jXYgdkYHGlFKphcGQ5f6xNEz4NYdVZTOjdMm8Rr9lhQexoQCBF+CFbWzdQuxts+M85jWNjGfr'
    b'7nvKwo9HYkE/gqX45DmCxJp1I57Qh8CL0xMzU8WAFQmF3fCV7zmhQ1JI6gjNnsAD2tsS6zXfEuG53bExLTBkp91ADnWCe469mRYS'
    b'huzPsGcSTXKzkl4cLuaxzdZ53qSSZDuU/DLM3tfo7KWI2EAdrIKmiyBqXQgiSee6rnZb5KvhHmJ18wYO+3hwrHgHz13ti9QYLLkF'
    b'8pTgSEGr4ZcZjuPqYZxqauKeccLKfRGtknJmyFRCwVDbiNI86xcRD0i/ikR4lC9RRpBJkDQqKYhGEHGAKBoZgDItHQ+ZFdibz0ch'
    b'mIs+hCBRasC0foTeyCY6+iLX5SP0hDcQ74db2OjFpF+cC6uxLpnIngk5L3Hd2bdR6YayT5PmCrVvi9wppbu95KWsv0k5LA9Dqr3U'
    b'Ha+/OT6mgY0lLoyDZ1NU7GlEXjsHN8Gq+Q3ItyIbTthFjbVdkBEfI0xOqInnu3ahM37Zb5HNL98TRmfeA0OkRn9+NqdsjyYxY7r4'
    b'hDkRtmMjiu0aSPFjkuYFr4d0dvjQ2t0pyvDEq4aNXDa0Afkm0tWOUwIYvmo/xMDZrd+ej9zUKFLFXrUJv/kzBspu0Qb54ACqiRXi'
    b'd2jRYR30NDYlQ/i0wRUC96OMcuE4QgLtRxlhs3GECNiBT4tvw0YtZb19xTaJZMikxNobKtlJFP3zFWurV/jjLTGZT84l6Tf0bovK'
    b'h8mZHNSenMmhrQXzOKgtPo9DW/JmsV/2DA5Zs1RxkaFHfkxiiwoEHZMgz2SPfERhBxJ+6nooWFEMQVyPd9ZlDNaLhS9hzBqs86gV'
    b'WWD9z7Gq+2Wu3SeVT1J3o6cnURztZEorY45iqeIZhsJTn+hxxnU03ZMenzIjCMw2CuKfNs/8BNY5SFeX3rXMRMX7lK7WJbXkt9ed'
    b'ZEP7KNFiZ120nAOtffe0843SN9lGnx3ndBZuSV2AHGlF1TOGRKWezg9PN/3rvKTGetmXaLn/zbojFVv3pPjZjzubSlcc3IzOd7x/'
    b'M1gx1kxVNfNFfl33UA+CdNIKIFL3C9UMwsche9EWfdiKAUhAX71c9iDSQL3IgCEYtxCiz/XDAB4SVOlsCJxHtL4bMh5NR7O/VUU5'
    b'fo63XYyVcXQ4mbUVZM/qUFyRVlebFGBqGHvWaOtHd5MXpqEOIdcC8K/kOmESgoW3/GlwjWd5FtAUWmveobbct8BIhuNzedqGvLJb'
    b'+YbslyKP7d4rhKwQGymYkIuvybr+AISNKXxKtzqIlxur+l+Jmyd7u9jVNYa37u/pR5Zb3HtYD/WLYcgdEI5Qlj1mL4BFgsmhJ98P'
    b'nmNnGK8Ahju6S5hVK3ebksbZ3kYx5q1ik0Tr7LdXEiiGb5lUH/6hd84QsoxZy0uiiQ79vy+R1moFEfGFO4q14NdTxZKrgw/NvFph'
    b'4+fO3rlPuyscYpziusMPQt90xUHJjt4O9wddUzAYXrPL3cHer0MqiDcec3awSJizhK79QfsA2VhA6MJb7drtrgVPCszch/N9jirX'
    b'7EVeXzfT7MWLd3fwm/b23MClZ76sgUcUK6CO/Gos5hh8g8baNx1cpWbo0Q2uKeCsQQ02o08++eR/beuqVYtW9Gjc3b8JjkHdoxe7'
    b'xgWtkDtN9h/SeSnL67ZY5Ys2cPNJOtsI13rn6QUEmJ3D9sc5xTZ1CKFqqdbzlcpBZYWhZPgH6z9m4dfV9Xj0l5u8UdmbMz2SorzO'
    b'9GCy2WwmrObNEGi3j8FzHxcZR8AfaxxrRxNnYOVm9MjXoKawuiAwbdodNdYWb0GiLkuBiWg6k2BqbAgYHilhSwgoI8Ohf+6Sj0nH'
    b'IFyOhEHJVeCyJevYBxcSmWmtrnblcq3Osj/DX7/DP2QtDqZrGtkn7JhOAE+syNvO2qvYVBaOiNH6zjvW7DH+fOSYgakdIkrU0PiC'
    b'B6cQQQAymmbvP+ju5HfmaR5iHWiDZ3SyxndsD1USVPemC5W/EfqRGR11AAheLBAyw+9dsoLJ4yx6qRXK13Wx7Ogeg5KD1AUgifRX'
    b'ByhLAaTHpvKNam+qZdc0dcFrlJu8hCcRk1anKpcFUKubiQ1ay8bmbEhVOXte/twuAkoyFQiLEUxvzCgTZDWzQp1NzQBSUmm4cnH+'
    b'Z9vwuuucvQxAymw0SlCuVmgvFxJHcvCavh45eEZ3HYMHqM7Bp3qY3A6uVjj4LoJOTkOwTwZPyID90zE1Er5zkvpHMmD7xzDF7S2H'
    b'7FzZ/D5sIuz30PkexFHwBCKuIloyIT7zcpmvKwiUq5vsOEZSwIZdB+VaLzgMmVEippCZu8IwbAbayBFVuVBlW2N0oY4xxuBiKDpG'
    b'FoOLoegaTxTQCCLFfFXt6gELFoeMo+k5o9PQnehSZ3YaOo7OChzp87WjhjtWzbnqyaTMaVOW+Lylw3mYKuzpMoyUjhXnNpC0RpTC'
    b'B0nHbDcun5oJMxDOvfF7HFGWRmPZeNPSVyOcnuhk96HpmVOvev8wnjbHfvMlKB1Az6A/zVe7cplD+s18PW/KfNvcVOwkEKHASKMT'
    b'H5n7vFirvDbY8f5CZhONH+VLR3Fp81ZB+/NabfOixpAqDGi5FF1crfPrhsHER2lSgQa2yOZmL/vuosP4iKiP5l6YlxB1Za7WxXVx'
    b'VayL9mHcOxt8AiERqbpvz40qwYRsJ4VCpvFrL56uDvWHvkkNkIID5eU7u701zIX8ayQHC1do6eEibvBb4IBgoJW3ixt49wqw/+dT'
    b'0PNO298H7oWukD2RXgffntaMUwm5jeeIko4g7fr/dfnQoR7yvfr7VT+BNMeUwhSWyD1tjr7PN5QNADV28Ju1D09F/hKqdGJWEbEO'
    b'fqqdPqRc53AsglHpQcYiaVS7RN7jatcOYfxRsA5u7/oMNRONCLYcjgP6HA+mCgtV7VyIWFXWxQJyi61B/pI223aF5FdNhZGPcwz3'
    b'Fi/a1kqnau4AQr0vqs7i5aRVi7UfTzCRgsnX25u8AwUk/riqqqZNw+xaZMHxfjYosV4/zK/WO7WtCzD6kXDW/ktbL6+LUuV1H9Qi'
    b'b6Pd8uFgi4ULl/Yq7IPzffwS8L/scpiTxGACsNRoAsD4cGiqr/N6G6UIKiaSu6rKXdBtrBklFFB+KrCqcOnB44DLalOUednOXQ3y'
    b'N/LgpA0r2Z72kKhwX+qDwqSESwXPOUlQ3/ZY5oVJ1erKVpOqk84+463QIC+orjpxJ6auGjEnpK61Cpx6vI3X5f8jQdcQkxeusHyQ'
    b'HbxU9iPKFLcg0/j9bQdAbYMmgeOZ4zdSFGRWisBcd5TddpT90lG2iJdxmXydl4ltQuOZ58u/7RqUIAq1XjZwEjUq5MhG9jIW7Jjm'
    b'k95bo33QB7B/g5jvGoihIGHrKp9v6+o+OC7yBgQ3az/Wthsf4qqq3s3bar7J63fwlBjDssi3BUyFWq2KRaHKxUNiSr0JMfw1Cqwb'
    b'xNjXkUPCPkjVxUJFIUjamFflXP2yg2bUaqWiB04NOe931lJ+VaDjWbDTSnwh7wIKz9342Fq1uCmLRb7uA6zVLb3o98DpTvVAgRxP'
    b'FNUDuKny1q5OD2x1V6q6uSm2kP77br4t1uu87t82XXBuerqgYNGA6vUMdYFu8kVddUIwntiJaLdui2WxUSW0CetXq3wJ3hUx6Bu1'
    b'Xs5XdbWBPX/LotKGHPI2cRpIyw2jhEYZMypUxOH3AG12WygYBqzuixadQ3rnqZ+fwStE0e60VQ3SknZ8SoEXsFpDAH28pJIZgLcL'
    b'cF38siuWsEGKzXa3blQf2LLOi8TYV6A0uq6TN4dmczOv1XrebB/mRwGLXl7lcO5GSojuG7UpmvniYbHWqhITQc0f+WpN61MreEFf'
    b'axuneJd2WxA0ckhIDY/+tWoaOOATR9VVVc+batUq4KGJMbb5telAF49zE1orUM0njo+6mV+pcnEDx8j8ZNNZ/Ka7+Og4nHK1AtIG'
    b'LVTV9ve5s6eGj6H0FhUkMBq+BkNPrDihWaDmoWkVZM7oA7zL63lVgEYpJVkxYDfmPsgho2bg+VrVbXzkQWrQyIkyB/N1lINCHidO'
    b'HJS7Fonuc8harYucVJyp0wIFZKaY7RTtPq4gSBoqKN4Hlvd+n3pGLOuqcplS7yyyFTztgFqLl8BDEAa/4VpSo/RyyIoVryVVS7qA'
    b'nqWktpXVoQha8+Vuuy4WUGodHKT+a1M0DTCqdL83+dbG8MHu/9O5y9iJGXJMgFGmv7sM0+a5dsKHc6uFm21UfR3RacqBX7gMn9lL'
    b'gdozkrX4y/O4is383FR356O1WvkkCj+e3hLeypEKIsOG5zwZj09gA0iyW7BIJoF+0taA4L0UAg3iW8U0ohZLmM3CNpVqxlfbDn1w'
    b'qHb8mUHqOoeG1w/SyuZlCYeLMialQmEuY+W+gBxP3GqOqpC/Y4dinUZpYuAKNS5Oph8nwqZ42DeuhESbCCkxGHsiqERXIzQhrolY'
    b'aWz12HroFELgPgWDG4NacL5c+WvBzLS9so6FaCtgXBpjwv6FI+YRxwzb4dleCEs8xlgMSG4k6k1bbTXn4TUcm2ExMi+ngpswztGV'
    b'Y7yttiKHi8he7JXJjSxKByek2XYmcpEtfqVj1rrpSCbl8cckmSXL0xM7WllcAoBIvDYx9oc+dmGC7Gl2cjgJ3pRgCQdk5GirLc/F'
    b'wXZAW22DHaDut2u4yhA/Ilv54ZRuai9XsBWpcoTgHVjHS5IDsqVwUK+AyqWVu6wO74l4mLtGovsAfv4O+7K62jXt/O/ju6Jsqrr4'
    b'uxq7qherS4zAceTCIAZp1OXAL1ZgWNTWxdX8/eoDS8KzqNQKWd1Kx/TIXmR/j8zcha0fvEsBsnSudodiGnvTktnZ0+3ZF5RHtShq'
    b'D26T7gqPa5HVHdyee9jZuzn2JjS0tbxsi0WxzfGZi+5PPe1K8TfsRAyjTBA/qF/2YWlT3MNOemqvAnz79ynymvXEXsUwPrVf9GLy'
    b'nP3SbzB79yvyGrw3ScdelIfSdupqTfdhKHjyNPU2sP+smQuUUCFoLQR09+Dx/e1CvU9HQ9Um9gyEgrtIYfbiUXPcq0Ddr8dWuyr7'
    b'aj8/vpcpve0e/evUWz+RSrtx79NLre6u0VuMXIRl6zSrEkwAdM2x6LrGsa2LqoYtZa+vgYizL0rdLb5Ik4HjJ6MK0A2u84f9eZmw'
    b'yRjAxEh7t6irO7iuD2UCsuEEjgHNByrQfdoN9af9DXqmTPu2n94GfYj32QLWQtFKk0/uXhrlPh3zHxaQydVV0yAdaZdxc50Q7fs1'
    b'u9tJvkDssR3Srxj9VBLV8e/RdvyNoL/djgeJPVrvetbYqw9PnYbeV5O9eoOvQ4/hE4kXpv7GV1V9l9dL9wzf5K1arwtti/oEmS6N'
    b'eJ/tSOLAwD7FuiHrd8wIweNEPvpkErW9tkKVh6+X4VEpbgt1F1cVF+VivVs6xxzSEetks49TFe9l8Rs39SXN1BDzXz+mR8rEhQyD'
    b'Fru2WlEEjsijO96u8tu8WINCF001fCiyDY+95/lfE+Z/fRo9gkrb4aVtjnttnjuMT/9R7JX/fzvkJ9shRxQ9ifWsq1XRmssxmHvo'
    b'N90n2RYPNlb+H2Vb7GpsqrJpAb+p2Tkzbb4GH+nrfL5WedJC16+gYWuVN6FdD4u/A0c7SRdXa8hZ0YM8Ih/GTYfC0Tbrqv1vbuT7'
    b'j2keruGL8lahLUlzA67EcSAvVUMURuRa+HUs0Qd7I/xjm6wPtPV9Zru2zfH8oQKnzOvQ3G+l/t/23m1JjhxJDH3vr8Ambawyp7Oy'
    b'LmRzZmqVfcQmq2cp9ZBtZPeOZKWyVFREZGYsIyOSEZFVrOZSpgfpTWZ60bHzAfoNvZ0/Oa9nzz8cc8cdcCAiq4o9s1qW2e40MxwO'
    b'wOFwOBx+yRbo0d0uroqS8nJuWnBj2NbU926VUD9XeWeMrRcgXcPD4uJkQ4H+mj6TxvcsL7tkcXITAcFtAJpiHy4OGBrTHu5o/7yc'
    b'zIZFPOwVk8Cd7lsq6GCFBhOur1Df6+2iqNJ6k1MfgR/DX+stuLCtiircL//uLZ64XlWrEEBT53R8xJfwi18n/ELaDLY5/X2brwJx'
    b'G0mZK9S39W2EpcJAmikjMOky8pUPA5JXLx7HPn4TG2CguQvxTWT8ARQOAIEhXQbbyk9+q3xLbcWW/HWZLm+p3/llP7mqMdvO6bF3'
    b'aianx+rzN97nVV1meQXm+RZylEKKz9NjT2JledKtBVCTQ14YCgoiQt6BUA3iURDX4HOSL37xjBj896y53W0pBFtwuVdYUEH6En9i'
    b'UUgXVaZsNLw4snPamhWOPW2QKlMcAxKFFkKWK/oWle1k1iQ/xHm/2rc6J9pQ+ECREm8GQ1IWe5InVgoh0oNdzGAIIJYjcEnXNSdP'
    b'Ftu0u1fcRSRGQTCEuvVw0osIqT1aYG97wLf1rkkDLTw/XJd4pP9tFEo40NowjxhP5nJy+oyNT49Pnx4ePzk8PZmcMZjNISqCMvWG'
    b'cFXPM5Ysu7xh3bpoGdipXYsg3H1kvmb+LxTvPOfGMm8wiEP9hBfgdgGxdr462naLrkkynf+5W+dt0Sr1nMnkbWAOIcP3suQW4XaV'
    b'SlHMjdoGtBWiwP3fHRu7hZiIKtBhEBBHEHJS/WoQhlDMgbbFX/BYCM/hXMQS3BR4HQUWg/WjnhEi7wSj0SjEE+hMjJxhPjJDH7N/'
    b'aGtwTG4xc14LGc9rhVHnnOU8KB4h2LMsa8+Y5pep+G9kDTaGyhgQnGbkonbYZ8ocDpkyiz+mzOAOjUXxxZR5XDHj5IS/75OibJNl'
    b'fob5L3En/Ju3r1/JyAyIiuAvHDJkAmGmarus8o69Sl4pfOO2huGxKr9RMEl5k9y2LP8A+XuAF7L6puKBeZBvqYXHp3YyMxdnyIPO'
    b'I3ZeQTif3rrYAYhCdrPOxVAhGw+++RyJKan2yJV1CZMaOxu6d086MR3A0nVJRJWQ8TLA2fDqZkyTGMvdxMlQufAgE+D1W0y5Ykmq'
    b'XnQYAWG2AKQYJkG+2gEzqjiCPtzEo17XOA9/8JTGmpPj42N3q7Nig/m+yjrJuJRxAKZaDnAXcx5Cjd+sPvCXxTa5BVRsHsY4xtxt'
    b'trvStm65C3q4s7HVgfnqC9Ep7Bz/p6grlsAGSW0CQNL05ehCicJLlHti4+wq9eh4xj7mH9JPTgAaQWKoGsDHbGRJ5L8MfHlF8ati'
    b'2owoDs7z8F9SZpKbg9wN3olNbHDrjHX3+2VgfMbZZnyQJ5yYuHfIgfEN8ycGwuZ4uwuN8XLW5JBnfiwThH2U5DgbIgwif5qYZ7Ye'
    b'88mpihSInJmydrdcFh/ydj4eAd0WPM2F0dqU2D/ienEu48FmIKqbnClWs0Qi7pMHlYsPwQxuQF+3zhs4pEYf5Xg/CSq4MpaDFpXg'
    b'gLCQLZb3mrszQvnHe72QmP2IJQGAw6QiltJ6cwWviVgjmw71hD8KKUaMyJ5jMY3mHxGfUpqkmc/tpRo8bWuidlpDWSsMgxKJ/t34'
    b'sH17IcgxZaORXaTM60GJDNEcQoSVNBA9mBvtOU+vybIcSopkUkcyt6IQ+mxZfHBU4O6XwyqBLaoyIrKuZhtwPTQ02QMTm2qyTZo2'
    b'n7E/F90adLfuF1gZxDHGsjFTtuvSqr4ZT+CI6H45TG4gIXGh1YhHbAv5mVt2OvuAYYHjrs6SW3Yo++4mrEmKNm8hLiy5BjVVaTts'
    b'Duqo1iUfsbeQknGbdF3e4CEI2unJ0yenV0+fKho8ByLMwooCHwDuFlUSfSbnMfPmOFN0M9RV5B4xAT8BomAVUzL15T+UTbSmhz7W'
    b'HrFmWTeDz0HV4GwAWkfVe8R+ViqlOMXP2NYQ7n7mI3bEdLakQ8mX+F1fGXeNdIlCby+gpq0jc2lI5VVio+0H+P/1Nq8W/D9dKUko'
    b'vb4wRpYjxWJKiUReIWkyS6pbN9KbmlHqQaCJ1FSg7CZFi6qun1A03cGhQw/UxNDHRnnVhfBYp85QdvTvGsiWMNwj7OyQncyOJzM8'
    b'98fww7fsWNWCdA0BHKvnRVgWS9w3MmtWumuuDSVKWZby945noX9f5xo1BYb2g263LfML2zvRrnkkKhw5ZoXnjkzNP3R5lamRMXPg'
    b's7S9ZmDQwL1DmBR4SSGZ+7llbc12bd60rM1z9vrVOaYtLqpdvWsFYgbUgRSTX1mXHdV92yVNx7p1U+9Way7fDKvAs+22qZN0bXLc'
    b'yUxVAJJ9GFWrQWKxr+UHvpWm7PePmSjKjMJ+bV+NGM+YCTm0WFKl67qZsR+StmNNfXOgJsLjb2Eqi/w9N4Yw7G0uGmHfWngzdjpj'
    b'P4DAQZKDW+4Zyo48SdeKhhzFs+9/On9jojHPIfyjbmoy0+dM1JsDawg/bTWgqBVlI2t3mzFX09hvlYR0hNRkxl4uGYc6kso5gyPS'
    b'NLPgH6goHXh4bPmNbTLlwxWEazs4D5POpB87PGRZvsoreCV2VuNq16E5pmg72JW7qitKZDMGmksrzUzqKjq7TTalSffHM/ZaZHQg'
    b'96dm8+6mZlvYKC1TNSz54N1asNty12psoswlL0o2Vj/Dmx00F/9EZ1MhfBx0CuY2TxoofaeXXhAPzci8bcAk9bmtBo+UUY4JL2x9'
    b'dG/yLmFzo94eDs6YxegMj4opCcAXQ9XqFSLXe08wqDoU1iT50Da4BL3A9pIMBkfF5YwdUwC4N0U1F7j2Vkem27CufFIszYPEtGgY'
    b'PxumKUFeaZoygWImKrsa3BTXWJ9kcDjbmCwj6NWg9NoUVOQ45512eMmokrGueumgmNhZY9z64bHE7pK+MYf8KGFMoQ2DJao8FGWd'
    b'XhyeaLuL2gYqlwG0E8um4fUIoccLa3sBcaEUpHn0wP8bTwKtJHZ9XOXv9UH7iH0H+gzXmdV5BQeg3vPIs/ALiNW2u3C0DzBDXYav'
    b'LlwwfS674/3sjc8teyMkqWTLpCgh3IOyN+pR2fUTiWsvonX0pzP7/HXPXZveqtajWjPrMxceYMOvak7VLOmSkZ8MJ2T5FMNwFW/R'
    b'gKd/4ha+PltJky+jaLxLUA8+pXPEkCqrYR827ssQxSVciAlMwUwl8FaF1LGvX3h1a/Jl36XsEfsTX79nZ3Ih/u//y2UI9jUDdwuv'
    b'sXCfUBwiOMocK+cu85fJDHjPN+s8Ys+Tdg1psYpsl5RnLGnhOYwVVQGejxD1hGVATMZVT4b8lQstp/6tkjekBycxDBkhCGnA9S07'
    b'pu1e1hENXdoEOsLmE37rCyPw9hv7LRufzI7Z13YHtJ3Q2ZPCFPrB1a1te6wtrj1NQye8iQwAzZGcgTn9gE40G+KvivJDOfS7M4Fe'
    b'2VnYFtwS0BLvNYMEq1tIkQ3r4LAgO9K9N/m2TNIc0i0JRUreymO5gW4Aq9jQR9as4+1cDuFUHUMSBTVgwX6BxnfnDoczJC0XnIBi'
    b'rVufMfZlCufw9/VMaGkMhjDEPgc3AXzQVsZU/iwMhdgKcD3Au5O6woPa0bLxzbpI13hBlM00FbCy9z3tloams+Cjsi/eHhYQGTZA'
    b'US1rXjnc+N08K/k4vyX6gk1jruHfuEeuo2BIXWnGS8OP7ZsS/Ll6IsjcRb30n4ukYiivHHpNJ0Fgsea7NiOasd8yuDUewyYhMOCF'
    b'GO4jRJ54UeSVM8xPyUpzgaUqgjrL0aB/gfKZcjSkugUNiV/DDL1G3vvk26tfmF5QZEpMF+yvvGdjNAt+deC3iSbnNwH5amF16Khf'
    b'vpqnVtaE5Ag4KFRBTLrxhepVXOgzyHxWrCoIVMAB8FuIVNEEjLjGIZMqDF5PQ+5aYVhCVTIW5gc5G2HkcHVJiddIqqi7su8wx5gZ'
    b'0DF2c43CvPyEm9tyFL3RhzS07k5mp/jiESaM7JbodVBL847HiflCBgWy7he4rxXb8Lj0P2hZtk5aqKM61nBTdsCF2gE/1S0MWtjp'
    b'n0MTk/8Z71hCud0arXWn8kerSzS1sDmDjIwKHTs0RjjBJyJ2xB4//WZ2+s2UneSHT+3FVDYeUAMUTxwZnEVpeWBFijT4rTjIj/gY'
    b'BQbMfSgbgEaFU3PeoMzTljJD6bNa/TyJNUZ7l5HmMFk1UXhuv9IN+ATce8oeh5fZh2XHgj4gkeaYn5OH/jnJl897PZFjFbYT/Azp'
    b'G4EVMGL/aldlZT7jtahkHkoR1MklkLYWqAKHkUJ56mFO/s6HZDvp6nt5FFegkSoPKyoE6qhnLNHIg4bxqRxT6Oq3xeVq1oC8gmwK'
    b'OnWv5b0qcOgC0vslEOavRqpubGhoRoXYejUeXfz52ZtXl+yZ6outkyZjK7CJcJf6M2ZkzYBsp4+PjzQROfKWyYlf5Wmyg2PMHiXP'
    b'4Dwz7ueICNbAzRmsCzhywXx2LP1w7Urbpr5O8In7k4fNYFdzqfvH5SaSdtjNdtIYgs4d6t2HtgfJwrsi8MUnoFd7M5SPO0Q5DjUP'
    b'sWq4CmegIw800KG2BCuS0gjxcwCJsesoMRUYoQPZjzvAAjR6AriXBBHxOKQT1aC3o0fs+11ZNruK8SAitm3qbd0mZYsXyLrJ8gbY'
    b'Wfiwt1N4ab4qqgzebosG7agohgS2Nm/RXo3KKKe7cOjODosKvOCFXx9GELOrfFnDPXWdmwJN4ErKsr5B5ipaTGlf5NmMsZ/WYB9u'
    b'4MGP93CIsW2HIlEZOp2UaJK4zptiWeT82HqETvI5TDDbpXlzCCWDACXjIcd/y4qOVRBsziBLQdW1AHqdVyiAtYP6LMRdSdcl6XqR'
    b'5SnP/IQqgUbhsVnfSvfh65Ma4uxRO8pMtKQFlpd9STCoGwtiluBVExmG0d9fHnJqb+0zaHKPRaag4PedS3CfxaZkuNaldZlBfFHT'
    b'EV52/NVj2+RbttnBTX5Xse/Ov3/95hx3CPpYCoSBoBeWJmUJWxTgv3/55u1Ph+d/f/4GMW3r7Q4XwD+G0/Za4EWDErjrKNPgkfA8'
    b'0A51kFkVXmbqJXrWgQvvdVHv2vJWbLEmqbgjhUB6VXfgJggDhvD6lo3/0w8nT37/9DHM9bDJMeSUfc3gx9/9QRHrO17HAs5L3LPg'
    b'1iddHh6xGoOHMu63wjelVFNl7W94x8Ly0N26vRjxfMtH0uQnoTCGh9tDrKeyYknim2FMSeuaaBcQzSrAwSezrasZPLC1YxIJvGwt'
    b'oKz4OK/SGstpjHbd8vD3I8fgWYDfPBAct7zZC3c64vc+83eukMqQTsrxt99dgVsdycdBeMWDCrdYNcuLbUBSmF9pl2CnKL35J6kl'
    b'whfm1pRpZA43G6qLW9jd/FOJUCC9SFFX8/NXf3z56nzx5vznt+eLvz9/8/bl61d002UNEYyCb4269uaf0DuDjpXbpG2/8rmuf21s'
    b'ivJKL64jDn+VBW8ce2A3DaQp8qC7fLMFUtnAHhhuJ1h+sBfivyiXfv51WZRghdOg7qOysGFp6MDG6hky9VbtvCl/d8lumrrLaXcl'
    b'JjGBX9RHPRzzqXkxZTJ+WhXXCZPcidxAVu9nUoKSIIFEt9FH8+8upXYkpmhEJCI/EdPqfZz3+6DJh9Rg7btiuzVf6Z1zzw2p5IeB'
    b'r0Upl0dxFo6NMEmB0vBAnUZjGicz9jP4qrV53rKr3S1Dk1hWNHnalbcCm1VXRp+G5hmXFasVHD3SNbLetkcoGX8r3f1cldBRJQLx'
    b'qST8UPUkgDPeUCwLV6wChyP/qCkhTsZ6exprcuo30SMINKPozpuC4R6WOYF3uV48Aego0q7engzCh4AuKnV3DqFAACtrEgB7FHJv'
    b'xkFKCUCwEBrQLj5Hcw4gI1TlMKZe4odMci5GUdsugMWpoCcbaV1gPz3uqpN+oaGmyhIm4IzG1vL3oLFgh+LUCZlWuyLLB+F22hio'
    b'xbNbAInrbCsWY7fZJCBEA2u6qxYCxOgIWBhzwFuNICtbg8n8oaEAEYk/zRVRGcL543UeQ+MCw0u3v8iGegS24gF4yRaA3GR8olZe'
    b'L+JgKxu5YpCbosrqm0GkIJvYaFXSFMyysWqKLIbRzvMBnhZGwxDSK/82NQwpNDSpayYC4U8gw+hrtUu2dlubHJjMbptUUEULK3uH'
    b'8RqgPDHSk/e8TQrJrJOVsWV0irysSKKbwBT72EDc+6BdVbcdSAYbbVqXMqVtssuKKKXt+qd2O2NzuHhl6Zb9McuW/hmoaCcjKIZi'
    b'561k0j3RWGPeVQXP+ChyMtLSysKeJlVW4NuX29gTGy5AlndJUd4LuRq5iGbDBMgim3cYrQ/sjdXM4RPBZKf6cXDwWtpiB9lI5OMe'
    b'hK7kclAGtMAllFwxJJHHPao9SqCgWtGDhVJRQjglG4nkQh0EipZ1leukVoFOehsO6GMAa/a19XoRdasUXFA9sBP76hyWoqGHWCSG'
    b'7UdtZ5DtRyxy6PbiNXPtRrCK/NSGvOQZukC/jGwCv9XVLW8YRT1gCcOtNOZVWV8lJc84LxebC/MBYw839qcQhh0wk97Gup+kWCzr'
    b'XaPTmfee0k4LlQaeOqQd2IG6S6gHUoOhu+jTZHq6sPUZB1jlvwIN5Q59mO0tCV5UiovoK5FzsPjwxk0eHAhSmfVuGMZQG4MSnKN4'
    b'Puk9MMfaeXqj3AwDVEV/3yg2QPfeQbgCTQyTgtIM0H36FopJvBumShgNAiaKATvOglf2bGq/2ZfafolEYxYNA2gDB+4AvP6JC1dQ'
    b'qJ7QiXhffIwzf4QSwmYOOAiOXOyqsqjeoUn4jP2YdGuM17YD5b1wKHDLCb/rSBPuTOAOhzfZ7bR5H4fHrdjW7FHYSc+ldvxbeOXa'
    b'VarKoqpvw98R/YlAZDm8XPAXdoWXAV6m8MoX9iwH52eI4hWWVuEjNDPjWHlkRzle5R26GabLFeRM2FX2yNWlVHPaaMrr8PDnKDDs'
    b'U7xMhT2RcF29SNvrcXA/wHMr+O0ab6wkPsmwFD5zFwzFpxiVQmjxfwAjRofY62w/I5p8HJz+ZGAbc4pD21izMHeYeIgRKDegt3VY'
    b'PuddO46zZ5Pc8KD/8hZDf1pW5XkGfmm3ZsB/DRVZUCbUDePy0WZPPNgCdZii2Vnpikz3LZHUJDcPWjGmqf2Mp2a9I3kjh4XxU4Q3'
    b'RZ0Z1cecVJ/GNPI+sFAS4kiqYVU5g8x4q7959NJe2pLveGSAPhHQq00EBisYIwUKdwR24j8lUnCZlpgI2YMMpR/tLSQyJkExnbmJ'
    b'3YxPDiJn9BaokddRoSazfRnZF0304Qxh7kACORmJ8Vqt1Kg8n0xrGEICBpVTRwAqJIId7rKNeb7knjzM4bTIvOwYyb/ixkt/5NdW'
    b'+puxJ8hqEfidFh/GJ9gcTRQgrzzUbQelkGIILAgCw6+Y2DskU7ImuQHXugVXU3jrIBAmYKZhxEMHDWHkahScKnR6LmycH22Z47bY'
    b'Q/S4eMm8BtZ1JSSEjE0TE0M+NnpqIYFkdNMnkrx7VkwqOcARweTPwG1rjJFwGrcHJWQUdX0MiSdl7thfPA079sW3aJWsgQe1dT+l'
    b'S7iIoFY3r/9l+ITEvCXOROWiG+casdr2dTnEygaBY6wswNC5uedEhSTDTg5gs3WYNU0olVfWScNswOFyejXLXUTc/S7EC0CTt1hS'
    b'dTzaVe+q+gauTpwVLSz4ExH8LMOqVWsCJJQ10v6XPXt7nJjTxPhBhYdjQle6awefYHA/o+gA6qlq7Zpax7PjGJ18/zsnsNIGCEen'
    b'u1uPXG97QvbEQ3u3L1me5ORQ+xBb+xMXh5IgHBeyEdpFWERlMtDDmRUtz1JQliKBQeDuMXwbDiJ5H9npQQwhOvz9NsS9HvQAnifW'
    b'ns19QoY4cNXUuy06GvZtFQC8uh1TYdnOdp4ynriJMnDA3yxZrWiaWyfSfKwoA+mFdxszqXOwlUcPjYY44qJ4zeNsPjZSgVe7qni/'
    b's5JM0yuGszWzUJGfnczaNjXPgke9EZPv9yzW9YI8toU6xDNgeiNym0runCVXYHv5FkJzT06nA9tR/HkU7MPHCqK4/1zRaoDEbJz8'
    b'nuZmN5KKW8xmH1LgUInRr1bBxAWadwyOxtI08F/oaacykBtygNRpvD4ncgbR15aAjXDPLnqfXsI3cXyCuIuq++DlynlYrX9/Ri+T'
    b'6EdVni8Idl/rX1FluxZ8jpGRvTa8nJF0DfErVBEGwmbhF0GFgqzEHX1Tbwhg+PUx+etT8teTU/Ln0yc0Zh9Jk0Mp2GtdHFdXPfZA'
    b'W1EsmRi3/vY48o3oXuP0Z9K0C7VE9GftUPg4/vlp/DOB/bPYer/UBf9rqQsuHRubelMToiUAiOVoydrUxhqrp2AI6+9jGw29Kapi'
    b's9ss4IHx7oWn02RbgCtevlwWaZFXaaCYr1udV3j2Bmo878quwCQYRpHseE3e3mrCuMbbvEpKyDLk2jeTVX66AF9NsAwHoODzOk+C'
    b'390anMdxAL8KJybK+Ob0ZrEuVmuqYl/T4tlUijiMQNHLE5xIC6vHcyiRYN06Bz8+CKtZIL0h7gdzu4P7zkDoTfIhBhlFtq6b4hd+'
    b'8MeAeMI/LIVc9mAUBQ2xoDvsz664Ro/2O7QJTqztml3a7ZqklHVso+h98CBmYdnGXcdt33HUm+TDcOB2DZkX0tsU1KYS/I73giYG'
    b'LbxO2+62VE5NtJ0SIVS11q1KnEgDgoaeNCByekGlDDFkVF8TfArh4jvvBdZl2MGzFxznQxXukQZYK6vJWx6zGgYsqiXoQMj6/dBK'
    b'6nAeDQOmCah9SeBZw4F5v0uaztdlHaibPH+XJbc9UJicaNEWoOMHno/88QH8ILi0bofNZQBGCdmPU8x8AE4JGcTZ1Dea+5dFF4Yy'
    b'WD8KZ/A7AVdXeVEuStR82nWxpXnGvotobTxw0Jp+vNzvllaRsGK9PIeB0YWrQUB3aNcYJWEACh9kKDEd6QFJJQJIr/PFk/dB1H2A'
    b'VcE7q5KmqW/gqPFhkgoOEewXlLHFsiy2gHP/ytdDC1dzXTSqI1m+NjY86oGUWmc7zdFqmlyItK6WRbOJKBqbctHl6bpCs0SyavIc'
    b'dLGAttHkFeQp4BHSCwhrDFKvzbvdNj756xokqBD+MKEIl4G/f415TziV+oA+wDLHYaCWPK17PV1kt1WyKVKxAQOYtlBA/ZpnY6G1'
    b'1ehXqz35XJekHYRYN3kLNR4CWET95xjxGgDa5S1Vc36FheDlhvS/19tFUaU1qDb+RyBh+GudLqmf02SbfwgPZZM0q6LyuF6HPAYA'
    b'mjqnqdgmZd5Kxe22vqXWIfxVzz8Cky4jXwX1JQSmLSRg5He8GxDyyyjjHVYigmXCm7Y4eeL+mNVlmTSL67qkxJwuxiUKaDmf33VU'
    b'AXqi8JYjPT98BncxYbzk1jd4rcQIYsN1g/+wj7uGhZJy1gi4Zmgr6tcs+BClzLVhn/Ggy6jv5mHPvS9RlAXvZPB0vaEFLTwPAHT5'
    b'MOnT4/Bhj1An4yXB4c+2P7t/opySmRNFmcJhGGPphcLz66FzeAwfOL0sptw9xp+bfFnznw2guknoEU3+EU8m8s9LOkyD7lNk0iV1'
    b'L6XcZQxQbFD1DvjDhwdIFUJy9iWDXJbifUdUAWNNLstjeXlDLGqR7uhRe15ewRNDptzR/eGSHP8wXH9Hzu/nfviT66onvakhR0mj'
    b'Jw93zjK53XcvfO790LMn9tgX8Ef3E94fsT0ygJYDd8teO2bwrlHjY2J8TAyrd9+MVKiyeNPcg5XFi5Yoxjy3m114mFUZ29EoXrAW'
    b'A2xAn1PrQO8Jh/ew8I37yGb6USkHKrthyIMK/owh099j86D9dtwhakdJgujgZOeQY9Z2DfxfsR1PZvl7Tk1wshkg9i+83tGBy1zH'
    b'/lPf0yoyeEZo4Nan7fXy9QHMi4OPEhK7zGKq329DbyN/mRNLfRNpl/l4AW107xFr0/uKA4uFMvQumIzXI3Rd5OG8y6QsIUxLZu0d'
    b'hV1+lfra7/J7N/0v6u6ryO4JGmNknrsIb4tGIsVRVmVgZ5Zj8eSun9mJbaUEnu1nZoyRz0RQRVOEB3GKnW3kpR/m8ce77Sv/Q82Y'
    b'2Nl0CWGH1MFLSr+vpj0EvDRZP7i3LUGIPb0zQwPf+w6FiOKRayZILD7TCtqz8Ht5apXzj0rDRVzt/FbrPMnGp8fad0jlXCOahxLD'
    b'gZ+feNVGZ5syT94lK639R5LOhVBijSD5ziUKxRZ1FUPFybkttrzKLG9LNzBTI+o4RZU58JvD5yJUla1vV0Ve5UYmwd9PoMT4rsrZ'
    b'sx9+OHyVvGJfQ9Low1/yprbq2z/ieRC9NGMSdVezd3m+FVl2y5y1aVIhAWfsGQhUyDYrixU/Ym//7uWPP56/YHogotW6vskz9off'
    b'sSP29PHvYQgtDgiGBr6yp6e/4Q5qLM3Lsp0ZKbjZrsKpZFDFKWFNDpFVkGtXZt4+stK1uMkHrakNsAlY8GITcBYX6d4lw9iAyjNP'
    b'p3MjmFNe3KDAgkDHi11DJjM+G0PE6UT5ArmdXi/kJecmz5Ot6ax6ASzhZNM6eMRLqteHi+RzD5/N9gRO+04DpxkG1heVc1t0yGWb'
    b'rGhiOALWnyEN4AxZm+UiQcxGGLGX80WaJmR0xzQMIvKTqFwAvbisMh96qBY7Gz9rPCLQeu6jFl90K6+2SSD1sNoVWLWpb+Su6bG/'
    b'gWCtYamQAtyLdxjeEguEAZ/19xwLBBKSqBfJhdXvoOtk/8CgLIZ/s9X94BXL8bNz9LNLh65UYqZI4oAHGqP1iNszQjrD0+cfo5HY'
    b'qWeEZKqowYZv23Z/v+WJ4tqbkFFsQydtT9iSosO29iTamCJQvAVNhngbcrLDBKDMQTVU/kn4PvFnJsZ6ILKbKMXpZl0eREN9sFFf'
    b'A2camY5jv+OMyhwyp34kzqfYPNylUWr648OygHTdSiM+nZzJ1OAQwanzgOsyEKyrDURWDpvnb/8eilhAzcW0Ka7ypoUs3iL1Nxpl'
    b'jsw84OzIQKTrVBz5OcFRjQItf5sU2WFX5A3bFum7lnV1PYPKMgYiY6RFy4os32zrDv7Fi/m22xzy65BZ0WfsmYGozdO6yhimS/+P'
    b'Xt54c+LY+D+y8WtuwPpuwm7qXWmWhr3K2U0BD5sQKcSK5RFWfG63ZdEdYgdQxQ3r5WQ1BEPw20Eff0YyiseaTYYi77uVPkgnoXvq'
    b'MOT0lXWPTU1dY8N5x2e8PywBYp0k0e2HJoITdb6YosxW2d2qIvprr8wbNKlwCzXDSSybNtb2YHOmi/G2XTN+NzljvBAN/MFWfTdl'
    b'kIsfS52MYzK0btjHT5NZ0eUbadT5FBuAvQJYriXbbbYOKzoD5odH1c1PoTS9W7hlWKZvcuGN/q1lJGoV6xWBnQ7BiFaXGA3m2NOw'
    b'nU2v0Vl0ZYj2ei5gPk+LbZm3o7PAw+Xo5xaKeoEYalnC2nybQD8MPOQP07q6LnipLvEsjMYZkMpg82AZvmFA4a5M24ZmxJywpxf5'
    b'MtmVHUuTDFyCz1SmKbgW63zeofbL0Z/qqoAUVNVK44AqYLfsIzwTWI/PB256LdES3bryGzx2Dqbsd5PJJwb/HRz1yyUYAJlBik3S'
    b'5U2RlOUt49mF2ynD10gQ+N26QPuTfUoK6jVJt4YC8OsEjzcskyRQQI3QWlM2Sk3nifaT/U/J+IYg0f9JSxtdBETkAcO6HjLrEKT2'
    b'ZZiuBcenForxJOLcR2ADzrpInqKFI7cur+WR5mWUt6SJkUNePFNCda1mDAldRHZ+XrfTBZsaiHluMvkgwR9ZMO+gmW9gpPMuQrVY'
    b'WePb7Qg/ToU93GpvTCSGwAEjUcELWNvG8ZgwgfEkIo4UfOOLOjIiB5BEh2XEjCxIIWwu3BTijC1MXZNkoDKAL+62xSzzbYEikMYY'
    b'gieHiR7wsJNlZJRZsN3FTALTK1JlQ5ESoD38sgfyaCOymyLMQoXJOZg/MxPPV3FI70XoU6Q2ROB49oCNM1nUztmB5zhVG0IWAPbT'
    b'WwYrQ4zwnXnGU2CqWhQyAWZrdBmuHOHVHfb7jxaQ6BuDcYUDmECViQGjCBeb2GMI8CYYXAGj/FlohRQP2ACqLz5efu/lowouHv7b'
    b'UPHpPtW7QbieSK/RIDibgLepbSEPd2yRNMxheiBRLpSYCSBNXvsyYtoa4E/Q3QWaRRlYhLq5d5D4ePV7SbQiS+/SRCkyZHl6BmAt'
    b'UWDv6dGEN6fE6UJgmNYdVyW8oTlaakUCI5TLEath07sW4dkPWYhY10LXxMpFVr73XtFPgQuRx+fBR+OAgaKyST6wuTgibbwhnKod'
    b'127kiSWYhxy4VY/Uz5YvcraBRcrPc0/5sGN9eW6N++YMuq3guiBuEkL13ubNIUfD9NjZbGZWivdpAsOZEqMweDtUJsj3M/FYPMTm'
    b'CGwk4dwkKsmVs1YhHxNh9gzRNpDjTkO5uWrsSgaD3zYsVg8g6xl0aM0JKHLQqjbCQwxaIaMEgT+/sAwgOWqIvOgl4vDR8+MXv3jV'
    b'pyKyJdTEyphuH/GBPiwxECujRe75PGkqUZZiWTfGuKu62aB9XEudKkO7NEQaqnJb/v5Ee5wz4RiG0RTMc8JK5+9g5a7Ir9rzkRhy'
    b'1DFMWNIfcFYCY7QVzMGe+JBWev4Zt1fJ+rHxEQ4hFUcUpVSxDPIAnBw0IX0fRPrsECVnr1vZh+BPeagAzaLHCPzFWNrSXCPUEs0c'
    b'ZSl6osROFZyxoJrel/MAIen29iJDc5rWdOu7nGvw5x0T+wqMKLydVJeEucch0ouW1vGj3DNMy+/tl58EFJw4lDTjfZSvGYu0zJNq'
    b'AQaMRZsmZdKMryfWy0aU1gW4XxyjEwVKXPXA8Wn/JbZWgH3kGMTxRjUGA2yTtda8LvaZWH2jRosfmvqmd8JyonVTgE1nJAYxmlze'
    b'd8IXHINZ0UJuS95WFiIci3+juRetxljdAoZ10XbNlD2rbi/3PI8xqbKJ1wgPibQlvavEQ7ZYQPhbF8B9MUz2K00U0h7mpemCBb4+'
    b'sP4mhBFgYyeVLkhV1B+8/GU4YwHqyMYQjw5/BvOhijtMtvJyYxxFIsyejUU8WIYLsqsWSVkKj4VvUuv6B6HR4vYyoDxTqBFZvtWE'
    b'WiebbU/1yEgrrwRkuKxPbIR+SZ8gEdyVDgPa944AOQMnRw+hgi/qhvVYVVjzcHHVNPrAO/wJPT69+AUkNL2Jw9jKF0nyeFdvD1/t'
    b'y96ZYO+Qr+vAcsrCH7De/s50kiK53etpQDWy3p68wmRhj8Z79UMXKgtSL2J18prEimpZVqJgZ2qbhiC8bRoElNs0yhahbRpa4TDW'
    b'AaW4+r2fe5Z8P8e/+MxDOzg6scGNCJfOveOTkG96hD9Z4ZOW/HQxUJefAlAyT3G4oGhgzcNFQgM4BxrfwpVB43j77GN95UADT5qR'
    b'ZgMcjiJMHKF4gBl76LlXK8eE1tfKo5Y68P5Ol4jD0CiRYooJ0W2cb+gTiRntnHgocESS+af5cHTdOZWyasBBZLTCDOGyqV8alMAv'
    b'rd93Qs8bR/ELD6874HdraoeJQ9+mg5MdDK7i1gjwsAQLzUdO2s8C4kW+6yMfzDHZe/CE1fZD4ytP+uMG/NiWrDDdpmEaTaP08I1Z'
    b'3Fc8PnU+XOet3PYV92ZuT2XoxKTE7NlPkdCJIGEiqI2ttB9mwelhzMYmChmwhqQZAFPpcnQBmQQuewQYWyZFGUonYEnMHhrv19Ig'
    b'4X4NDQr1nkCDR3yn0e410p7S8rToCVd+p+F7q8Dv2yzaW1gwEuPmzDZEJIaJNI0ThEumYN+EUJoM7Fhu2DBEnywIDzyCuydw6G7S'
    b'4Bz7YUY/ewuCHjLs19IOZerZ0IN73q/Xz8nOvXtyOmj/hQ7icFvB7g/3GuUGFweijb2+/LCJeTSuJfKg5P+rl7xyf/UC9m3h3lXq'
    b'7+mzbOg/YncMu5PGOOxu+IYeRps7Idhre+87jjuN4Q4pIkQZCgCExOvedjQrRsfKookCP5cTWadvdDlrd5vxJFISTLw3mV3Yz0uS'
    b'pnR+0MgwdO2pS93lJDRpnd+CeA1wQOEmt5/BayjW2PJtSygG7a+e+AJXK6EiCFB+qcK0E0QajZ5mCg4iSXjuCnMXI6g620XLIdk7'
    b'nKbu73cwJpotg8/PRC8cVmQv4rl5kyzZigyFfKn4wk11EhDJrzqrCn+BRA51roAqhRrvw0g4nJR508ku8CDGfmSM23XeQPimMDXw'
    b'1maaOAVhD5JIOgO2myZfizSMNGYb5m79lGH05d2xAn0xQzUPemBzlvPSaFBXgn8SlxGRMUdggcDXuawNxoSLB/6myoCxd3N0rIa8'
    b'LoAUOHzxzu42YlR0RuZFSYgz311yyCAnpJXIGWfpUyZz6CBO7Bb+ux3bAN161uQJJJD/0I0986XeCuHBwKsw0SmPLvH4VRbZ1VMQ'
    b'nbiHupdcoJ8OWwjxq3ctBxWPhnMGo1lQ3yTXiA6ybq7+i48J7aO+czl4O63ruhUGVB9An3xhz3Stwkl3Mwkx92IaR5Ei7uzEjAmS'
    b'WSFA/M7vInD6qD4P/G4kNliuYFuYaQsqqP3EnSetiEF5Hw18DyRUUIvUO1gNACQNLBZn1BiF91oLYzEonptTP049vxfMy2AMVr1R'
    b'82B8XN8zS5tBDxjzB72B6h1sFlni18rSWCzha8QNpN51+vGElzPAnIZi4wdWjtOUf1RzkIXcDBKaEqbedaDcCDTo0RciNGRBhBW1'
    b'FcxfZXkJJRAHDpPDh5W9xhwjn3fF6+/Dvxb+OkQJObY6NGrTdZ7tSmtpsx3PhIuqapSbxBawm1rP76ojxEP2Bto9Jjrt5dtg8wjH'
    b'KqzD+gk3HdIH5ha4Wx/Y1BICI2+bSu83EA+kk5sYmdMMBmTKiYhTaRhB4ItV4l6ErMpUZGaf5o1BCTH8TZ+I834ZK2E5Oi9N3wAU'
    b'XhuOCi9CA5obFybXjDSkc6eJ9CP1rmQDcAUvcvYH1eXeKI3XOk0iJ8mpuGIaPy4gowMnE2jPabnL9Cu14WARSpsawugZ7XzkxrUy'
    b'nKAy0gVB0egU4pkrB3ekWsenpJJGnT4zEkadTM54qigj7ZJM1qTW+VDo3SJtK6jY8TUIJDWKpK7tp0UAZ7zhX2Ou4C+Jff8ZJPZ9'
    b'mKy89sZ76mZrezw5Y9zCxEQFQjE49v/85//Bdm3esIN/+p//6//97//ln/7n/2L/33/7b//0f/7XA9bk73fwmi6Qi4ct4Y3TsscC'
    b'F78EtmyMJQ7ZERO11iCH2yZvVpByZwJBp4xXamdX4lrwCFbm9qDJ2dWugWxAReWkcGZvd80ySSHXEHeAfXzMrriPN9YmZ89evWBQ'
    b'q0Dgu1kX6ZolTX6UNHl1gDqI8OnQuwQyzwE+nHaaVJh6Dn5YJVuBZ5zPVjP2w8ufztnXJ8ffPP0NE1XWYexSuTHE4fOX56/Y1988'
    b'/f1vGHjogR0o79LZRJLuJ0iVVECSu+a6SHOemK6olk0iK9HmuBJVLZ4Zis02SQXlLQuNrCDpuAFBZk606Qo7ooRyPX+ExoZupBal'
    b'iUvcogTjj5NT28/Tj6VlUp6FP1Tkko3o+ntsJP6tGEV8ITLkF0voRtB+UWbxCgWLMrtYpKAPHs+O3WldyG51kXuAhC9+vquHm5SF'
    b'+vJyhkrO2MrI75cUkDoqZMuZbfKkGicfinZ+4jwWlZiZjU9iBlV7RF2QsT/VKUvalKeJEeKDHzePjyfU+uJ5h5GRcx4W+ktBhFa6'
    b'Wo9I0YMb3irnkkG4yRzCTaz0v1geZbfd5g0VFGlXLaD7UnmF3L4wgn8yiZPWvoRi1htgNa8rw/ZlBLkYS3AxAuu+bCb5in8R5LgM'
    b'TXxWtEU1VgSfvctv27FT4kYh00OTj0x7dQXhp6qnMCkAIZ6Gc3aR8pIbfoZy3CZqrUevko3zDCbL2pr/zUvcUqnsZCFCRvDuZ9ye'
    b'1EhA6mNdEfivx+q/nqr/OjlV/3n6ZEPhaNqFmrKAbtqFznOkfxPvcU9JNGr0XhADVd4bm1iMaLUUHGMLJCx8IoQrMJEUsJck/0nG'
    b'UBmgrZMp8sxfLfDND8xZgS3Dn2wn1Iu8peBcsuBpd4bp9x4fS3Vnyj5Cv5+OHh+TOoF0tu5zDhgyDG6X9pwD7vAs/qVyQkDTRTO3'
    b'4eBaNG2njgfOthjZOZXvIyLVmapShAZv/MmK9AyIe15oCCobuqqf1ovCkZw8g4wYiObqQDkiFzXUJNptqkvi+IKsu1BT6CuyQ1F3'
    b'SERSqhNN/GycY874KAJvkg8DyQsHyL8Y2m6SD+PJ/SjLWRcfUGnCtl0Dj5UjpGrbNZ+fpvA0E6FogIaKYp7GIYre+aj4f1yIf/8N'
    b'zNIsAKwGM5iTrZFrauPj1QJ0Z8UJxBsYpHu+s+Dg72MB6svHs4diY8R3b96Fq8SdmFeQs86EV8IetIwy8z1pGGdbi2YPzau6ylv4'
    b'LZQcHiZzl8hn8C9/1TAiv85Usgi1ZPhjP/d7+iJX/jD/TOgpWCdDQC64jK2TVPzJlUIAoW0OX0rjZtV2dfoOzc9qEW3rA/7Uf92p'
    b'8vHzZ2//bvHjm9f/7t8vfnr5/N+ev9Gk9goQQjI21bMx14DyLadmtBk4P7wE5WBose/UBqakbYuV4c8g/+ixzHXLi9BwbY0e/lRR'
    b'nnjJHAQNFe2x/6WLCgcGYfho2g1R+yeegd1MEkKc2ckjBD2ddBG4EWBWZQ5V5719oP/zzON99o9Y77BnX2gM4Hem/4FpB7wpWBP2'
    b'aC6nptGIHNMOHE+hDF3A/9oXQKeuUAilDRVFaBYBCqEzYULIYkuS1ruKr4j6L3NBiiq0HPBFL4ZqjKml5H/fbSngnqpwBNeBz7Nv'
    b'DQhc3gLQmGziE3gcyntYPnkHeAsekCry9GGOgh7x6B8NOAhl3hGGmM93UPRYJeurf8jTLmyYfIBT5K/zPAiLf5MURMZOYvnmtrJq'
    b'dk+uNqHBxnLdSd0Nagfl3TyEdP/DiMZjo+FK88OeTd6IkrSDFHKykMI8enJF1TvPi8N9L3Zj81GokF1qyazmbItOOXOQTdf+C5Gk'
    b'gXcTJQvQ7fmacLd9S1hMB9lWHZ4YpjkFtaYZKv+C8s7Ti1XuBv68tHABAwA8WQeFccQeEMkhh9tD5lCza3Fw9wW8X5Ob6Iy8ggu3'
    b'FXrfqTvjXFy7jcoFhllqzy4t4saD6wLDsmDsIZKVU8jBrqKD9P2HRlarfUlzfaferu/Y2/s79fb+rst+p97SvXrjjM+fZkRJJs8E'
    b'EupJvYDJjkajSCdKGdNdOEqaJ9BlnQ3H8eo7sJ5kh1jHhC2LD64fFpYd2jb5lo3zCmK/pEO5Gg9ACKTbJj9s8mWTt2uov42eeV6V'
    b'OyjxtIACdRN2k7RsU1/nGdttofL2d+ffv35zLmpvN630/Qj4WbE0KcsZe5ujpwm6iVV50ujmhgMZ948QByVZdQzDiwuom8L/I6+6'
    b'oru9kD8bNZHwp64lISFgzoBcFZjFa1N0HrTxyWwhApyx7lVdea2cz2bLtK6WxWqxLKpV3kBlLr9PAsSal+2BzOskbbPZT8UmRw8x'
    b'WQUz6yYzABk7RV/0Z34swPXLwC+jJkdnhEbQzPihrVSiZsaXy9cQwCGGdmW7UPYdI6LyEg7HpttBnTKrUN6Qw9J0tSOTp5qVg6Ry'
    b'BOvmOeH/KppK0CQS1QLsOR2bTEXUa4rP6tfQ0th8zry5E0qadPSwlbIHodHMpJII25PLHnxv1IBazru1rYRSDm4NZ+GXSxMsdjgZ'
    b'iaOj6Ew4e2wmf4tUiHwSQph6m5mwjIT7tVE6LXUBMHpApOVkaF9Wu0E92ZaVof0Yrfp6sWQJdcMbnfXdAX0Mzo2NQuGAEDi2eVos'
    b'i9Rws8+xfCscl+il4NVF622oiqr43VFhQLgd0Kks0FWgEV1twG+kqHOnu+qwgYk+zCH59zZjkDaLylzNXZNXq24dZcF4y+AGN3l1'
    b'n+5i7fqkyaqpb7r1AgxVSTlkX9kN+tA3RftuD+QmeBA1KLaFrgUgM1LxwBN+dSa6QvV/SNv+rlAHvlNHRsv+bsxql/t2ZLU1uwqm'
    b'zQdtNfTNaO8UYrBgYZCBVO5uO5AN5rDs+gyDsYpmUGw1jBticXUuV0EvKTkH6Ih0e19tAnwT5aApHHaFCoXfZkl1e1/NB9EGJ4ci'
    b'zleDTK8gskVYH8I8FxhwXbX5BkqG68PQqj0Dd+xycbWrsjKfxtoFjgS/AQ+ElQs1vCMjO5Ut7Hl5U46VOv98VLLwrAiD5YR9qJE4'
    b'yOExiNipBN3tM5LDnbGP785YA5rbWNq0p+yJbdfWdSD8Sx1imTKsDDGOrWxoXOYE4wdrOM6YE9g9yT9H1L5eLTd2MaRThRuQvHQN'
    b'tajD8wzX3o3NgSgP6+g3vSSUG95lNplkY1DF4QB4YIBDgv3P/vKh/ubq9cXgn/3Li/K3zKFEkP7ZfaP7SaYWUeFnA2L5vUYmxixf'
    b'5g3ER8XWNNrHAAxmh/H0Amf3yk0Q2F12doGzO6cl6EMvjOt3zUjQh77JE8h9f5cORFPiGFVLJdXpnt1ENYqhVYPeC294vMJ8cV8x'
    b'GUDzEDISPDBTkY1H1cxIymJVgcVfigOIn4hDmjjrbbvYFLiOkPY7UxnA1EkE+IJQ1vDMZ1Awppv/Ni/dmEhIUF0yx5BrAdEwYkol'
    b'HVm5H6n0F7X6HHYlgD98QiYGM+j5WCIg+7rPNAOZGeFJguSmQAqxYUsRzD/2l1qOwIAeaEnuMd09luWT82YXzHDnPOt5Ge6uOpn8'
    b'LoZFq5gEgln+fgeJxNNdo9PRi996g+xPnzuvqjzsqyyWeQflMTkeCDW7zpkqbs2+xlSFKjL8+6QoIVHkmXCCAgkKUWarPMNY86yG'
    b'MPZ3RVmybbHNy6LKiahw2ekif7/IllP9703eJTq/hwGm5+1lWjU/TulHM8LYoHAHAtPJvu3AdHPUal1jqOTlQZdCE5vKpgdE3gPb'
    b'AzuqPWCDkGV1bQjBHtY8I2GO5GQCTGotl+ZTbT7BcGkbfb3y1X8dmXj6/JLmxDP2scyrsT23ySco3thO2YhA+fzZH9+wj9YQUV4c'
    b'qJ/SZNUcCP/Q8UGVVAeTydns9DefGBygJNIoPqxdfwB3ybPZ6fITw3+TaMYos7j9bk7jvM55JLyAOph8mtiY7hT5GaRvLPhTiY7H'
    b'bn6OU3gfb+oKIkEPl1AbMytvzYwVIk35v3n7+hXYVQQ68IFMm4IPWOSWmLEfIZvEtqlBSMMHcM1gSQmZOm8PufNEngkMdOoYkFHO'
    b'FlOCispJYeZ/JvarV1VFJfS2Ny7WvxqKzMpwHsKsUKPfMxeCHiwdwAQpOowaoYZMFQcSN1S67uhu9RnhH3PGIIPXBUBAmL4oVup6'
    b'UpOCyvCx9lNdYPKNKVug8wSHBLcI2M1jIocGUlnmXV00zoM9xGWBU/Zo4sVBOaOFcS06AF500ed7egjwl9ZVV1RGjjeSbpAjI6+y'
    b'sW2bNP9GkGVN2qabC/5PHiTF/9t3PAfKKu8WSQWEnQgXFxCRagwT9jU7mYYHIOh3xhZdBKqCpAjc+UZ2KfMkKLJHmgtPMhuBTrAw'
    b'BIXj8CGRqOfrcOyHhQY23a3pSyQRGR8Gjoi32DZFqm9isIbm72IpzZ8GrqjZZEL6LnkDasAYgykh/EG53ySPOT8PZTen2cABtuuk'
    b'ydvFOi8za3Dm72Jg5k8DB2U2GTgggF1kya20IcBg9G9iKPqHgQPRDQYOY1epWzt3xbeo438VA/M/DByg33DgQLt13hYtujrugGaW'
    b'ILa+wdMPf1TiO0n+g0b+yZbV3MOLyH409KjhF04Z2hkPxoE/Xq4ezh0VfjMwNJM8N/wIRXnqqH7MccoIU0heogGiCaIUhTib2EEr'
    b'GokOUuxJzUTkLCFDzDgXFHhgaB2DcHNL2kW9XOy6FJx7DHfN2a5Lq/pmPJl1vyzKOkU2HKMSMivaegnF7ToqidLn9gQNe7uev/rj'
    b'y1fnizfnP789X/z9+Zu3L1+/Crfj/rOLdp3ops9f/+lPL39avP27Z0Q7SB4jzurRmXN2E+C29yP/FwFmXW+UOHG1QGk6MWE51VxI'
    b'W5AMxBMjs31fGjpCDvwAQ1SIBo2xq6HygiObe3qw2jzAiF188YE7F0exXUJduNCB4WKXo+ooofI1mVys/tuGE57+8KetOdrxHcVB'
    b'OxaeANZ9eDTlFxXdHvJUGgWwgtcj8o4IOa+SAlxevXGYJVCMu1zA9mENo9/28Yg9Ny5+6mK8a/OWKoSlPFLYWNyARfhAnrHkqr42'
    b'6WHePmP0sA/aWJ/izIrBmAkc7BKAjp+qicRhHmRhII0Jw9YJnPCszbcJ/KDNFfxKz25znZw/QIXoupmA/etmm0+4AeTSs3AUeYtF'
    b'W7q8goSlRcWq+UeLQy4ODGl/cPkJMo1UKYKZA3LB7pbfKzTM27tbeZocVoh1TZLlrbLnKOOPNAu/KJZLZOg2T3eg9zH5xoSZZalo'
    b'HelVJNPLsq4WyLK8y9OOvTr/8+K7n/89O2Ln/+7lT+yIPXvxgh2xn968/BMv/NLO2J+LKqtvzliZtB37wzEDHdw1VWOmUs62YhpJ'
    b'0yS3wO1iCJgEtahWoLcCG2JUNiiachKUEYlTZsFRhqw/FpBrPrLI4GLYiqJXQ0hn4MSe+KtIxIgDuUn93mf5h6KFoE4nryrA8KQ+'
    b'WD1HdDomMNj6pFSBAcLUfiVVF7C9edJnUBtRG0bYsNYOny9CCGCSXC8GZRC+jXsaeDrylO26lGcin2Wdr7ES94hdVy+XvOchOi87'
    b'lJBZXnbJGDh2/gcni6VJdj6Fvpl/O5dD8aL6Nb9BYzCm1U2XZ3200a9lu6p4vwPl2keJXpTi5YtIRTJ3k47qRhi2bT24WTZCLjf4'
    b'kAN2Qfg2mD7zOeD0r2liDWXsBQwqbLvjl199RZzIO+EZfSuzLVZERldpvgr2aNlLccaGvTTYCvM40AbTuKnUXyyBTq1Z0eKihe2k'
    b'FktgZL4mbk8jDh8Bi9pgH7EX/NxI10m1ymksi6QsF5weuBNAjJkDlils2T/yb8bgyey2Ns/iIhk9RKh0g93CfK3uYb0WHbdtxhqn'
    b'O0hMZg1vWFMUOtCU4ziUI4nxUnLVjnnDCftX7CQ/fBKeWO8yCZySAP9qDgif4sEgxvQt/hLvQvi2QXI2oSb4z23yLy+N/r71uhMj'
    b'GNwfKCN9nXEqf8uOB2N99uJFDKlbTiaCCfSjMCpLQeh/rYC/kFAVxsCOMlrs/+CAkMrNUcynB1yEH17lSx5Uz/2+xVJP2dPJsPbJ'
    b'ssPhqebprhneGtdat8Z/xls7ts87S86A1CQ008CdyAmZfFAL3qis63fgRSKt7X84dgAqwYXCBmZxpouMzwVZyIAygxbveKPzFXR9'
    b'ofvoD+uTuHngpYbfObL73dWsAcTuaeDux1MuL6AGCKz6bguKrlUGp2uSFAptBsoJ8iKQ6p9eIRcDkrSiqM/hOkAETA+uJAWScbf8'
    b'dZ6+MwZ4ZUiMgIenBgg4ynIAQcVt3iwXG7A96fjw0SP2+vVb9mPeICtXac7eiHLuGsb47+XokL3ZVUyJwzP2Ud44Znyj6G2BQNs8'
    b'nR+0eVpXWXsw+eTg+p7XWzmCorLiQrrNm6IGDuCOo0nT4Z3mE/tP/Ke8gvemLndRnfNyr+hfgck0AOiM53myfF0PRGFYqCOm8R9M'
    b'2cEBaqV2v96Q/4RusWfsoxMSccD9Zf05glcOAY6uOJOz2ZOl2+A7mXCe8SA+orHOSc9B/F41kkD/GkV4JLCj2zaEAbZ920aav10n'
    b'zZYaPrxebvNAo7rpiqqmWvEvdLM/JR9evKBWJfmwyDK6zfOk3CQNuTbwgW708g27bgetCIG4CC550h0iAzEUEuR6JZ0Za0Mj+gmE'
    b'KUvrtmNjqOPTFlk+ZVfbdkKg5PIdgBdX23axhcoLRYbrcuqvC2wJsBSlybbokpKNf377gsKKewcKHgvAxa7NaJTnWNmkFyEvgNKP'
    b'7tk14GrXwmWVwATRVcabEk1CQAPvDugRN0aKl7eTADYJyFemvKVRvpGim6nawhwxLgsRrnUQ9Mc/cDz3o5AQ8eZNT0Sx6VJuTJRy'
    b'48/WMFEi+u0gGP12oKLfKEo20amTwWVI2Ni0ZIwZxQSa1Bjn1ktehEIPxkkQVcbsrUmPmg6Js4ZLcAYUqXz5nEE2rDP20akVLhBD'
    b'4fEixYxZNH+9evH8j//6I1Gk/FMIZ5Wlq0XSLd5FsP7Y5GkB78L7od7KZn34v5OO1rsWUlJIxvN0IiH/ZNwIhw5z3Ruhe6EteyhS'
    b'q3xiDLeKOerh7L5K1J9zh+M+xpeHAYOMxVgd9AUpHkzZrzTJ8O4UdWjP2MfoVMgIwYMIWh7xwoRj6ceeeRLhYj7yV/kHqOYmovqM'
    b'xRG6av8EQiGBB1FWhaaQimxQP8G4wIF9QBDNnfqAhpE+uG5f1XecAY+08/G/xdg03C1HKvRDxaZJ+TEgis1F/Npw05YuaEwGqrFu'
    b'DVn66hJuOkMC26izTgnQG3wLxGKLSVPATR5dPs7YR7jWzP6hLipw5hrDfv8w4SkBPmB1peVqpqbCsSw0Fu44oibGnxDG4pmuwXui'
    b'eKqra1Qf5SVytslGE9PyMvoP1YgPQ9xC4UWgSmusbDfadcvD36vLvn3R95KXGnUSuRlO12s1w8l4GVYKWFRnpbM7eg30J7eRU25R'
    b'tTBKf/p5xVTlK3wQ5Q3MCCuzhVoYK3iGt3FCqqwkQm7UDm9hBEvZeVeKSiqvyqCuW1GffVqDME2lxCbxhEA8XFhUc9FicsQIvhiY'
    b'h1NI5yuRacNA43zx11imkAI9v6UwBCA8TGlSZQXarLC6+e3iqq7fGXjI7x6W5a7KEpA2SalEg8+B6ku8+QasLnnVgjyLISPhXNQo'
    b'FYcNr4wi2iRpU+twU2wrH/slTxoQXnMjVwmx14TwQighu4ItrDBIUyzNuPVx7NolJ3coHEfhtQzAhE8qFpszaY2quUdnVZPOJZKW'
    b'e6JwPZRD1tXrCSHoFrgPYiTqnfvoHAvqMFwRGU1YW4M4xY3l/S4pi04EHwks4lOoqWEw0yekz2EumMei1m5cbJMqB09HMIU/eb9Y'
    b'lngC871hraWCRZAYTskVcN5KJzYjEZGLFcHg+yCkaV1CskK83u2ywpo6onMB9sUqHJIodraxS8Ah+DnlBC2UaxNJXvXkF8KrJfWu'
    b'KsBzGq6U8O5OMIMLYXrr3Qm3HrILkOVdUpRBzKLwJVpxuO3bH60PE8Jmx567eMyvBAbtahERmNsSNI+HkZdczEicHiXlh31kWhCZ'
    b'Ao5gJQgANxTD1a34hedhTZqcnrpVIERDg0zCwYADkq2+mjgNjzXRN3H97uk/2MIbQxi3Pw76MhIcRPjuYo0ggNXvXmlzqFsIMBV0'
    b'Y39dNUXmBnvao7OTS4J53WxqDtDH7DgVDkQMRooIYrRhEGsvsybK/IruxMm8kAIoTgKnpdsFwSvhnuyRY2YAIdC7pMqSsq5UQ9tn'
    b'OzQ42VxkzNRYVHNzaL3Q0SVzUyt7Q6f6wkZGT7EO7JSzg9CLJgM7MJPMDkIvGlDY+9ZPxobfbflk60GrZx3J5uD6YwFCAwsEvBtn'
    b'hRxVADLOSEaTrt6e9OJFII0ygo62OJBILetDH17h+1CtFqtdkeURtA6kvyoi8szQZ+X1P74mRDvrNi9HE8Y/aCyDGDfSrmcoQWZd'
    b'lfVVUi6EWURkJkf1exB1ws1JIvX2ts8AB5Gsv/mw8ZEERO3TyYe2qxZJsVjWu0bX1ZInlkpYqA5IErTnaHTaqPfVwMlIdxEVFaEe'
    b'QlqIAz9UG+npxtNJ6G4c3WR4Nyp7PlRYtCSL08IEFD1xwYUyp27kbcP05n9W3aIv/2hbJnC9cQK/2EgwFCTl/TRlI3PI+JsIA9TB'
    b'al8q3lgm7hYEHLig8qcI/k8DouIVoOQJLHIXgHui9buVPLTilzQDFv/twKjjlsqpOP7cJVQ8/H9DxNZbQF5tmZ7Kcl4tGQ3XX1XG'
    b'iubopwVZdOYvV3gmXHwG/gwGlH9uLNQDEN4qUNNTNWSvuiJ95UP2rDAyMEvml0okf8lKJN6CfqkB9CvUAPpS/+Wvs/4LmKw8k6xx'
    b'2hNfnbM/8LQ0TBMINP7rUQhCAwzoBcK28bmrD0qrkJFO2Mvua/hP7J2CGGNenBS+XlR2KE+y48wRycj7IMMLZOEdSQ9SHcU28Sno'
    b'Zv+FKCL6i+UD8aXkxpeSG2SxlV+lqsSX4hr/OxfXIBa/3nbFpvgF0YSrIpinMj2E8OBMDzQ6kiVYviYET9avoQJagphJYBKtH9YS'
    b'REqAkii178keyKONyG6U64GoAyIyAv1ieC3wICjHRmMeZXkCr2BN3qY7o5lT1dKWMD1tCEa3W+jXDTFsNzIwCg+f+SkLWtXI6kdr'
    b'tcJ/4aqs03c4j9An02WNrwZMWqfApxbVsEDDhnL8jOjrou0bgP+Gni64K7DtCdzTjC5VTbz+6/OF7GZIW9tIGHdQDvXT186ajx3J'
    b'AkHt9i+WuyteKiG0dXTGTPfBmfHpr6OEnlmAbt/OQsXr/vmUgHFihuR46GAgD5qq6mZfrWSLoYit1jT+XWXyqWzZmqQMwbh4gttZ'
    b'1KWnfYMcJNHNKhCFHXwcZOEdKTAFHHUcNJSXjoGEdOLxpkX7vFizCrjFUP7hzki4hX2TfIBjxoYRH8xd+6Wc7T3K2eoFT+FZj6vA'
    b'9klJP+9GW1FaM7TxPFUUx/ps6MHSrEh7YAyZQW/LwCzCD9tnd38Ld/rg6Rww5AO9y4XD9UKGDQV76mtI9Jeuk80W0zm4SwrbTz59'
    b'eB/NLRh4WxZ1kW0jVeCxf50n2fjxBJPwwTlbQ3GQbo516pqsFblS5J8w1cUcB3z7kJHH0Dr2B7yMj87cvsyvfrAMJOzAnJyackYN'
    b'ePfqH2sSUB3sgs/B7oaA+aOP+RuG6lyLdRqCbI9y2b6UMS/G5subYwkNSCfBZ9/syWdhdPuxWp8bnTePXhe/vaYxzGFw8GwsAapn'
    b'EHB048XNzAt8yD/Lo0LE42uv+fd5nA2eea+HlDeFfg+svWYy0B9s8ISUE4/lkGMsFh2JZerVoWAtCosVnkAisQMYTGntXhJANIfz'
    b'QLkuReY/zQC1AYmgvRTQE+EBZaX3xSJUzcnxscxtVTes2MCsWJMvIWqZ3+Jctymd79z9wubxlo7viZ2oC+eGe3F1KwsVzPvLFIAq'
    b'UWRz/j951RXd7QXqF0U2chxA4NeuJUAhutkGXRWoX22KzgHXH9wmaV0ti9ViWVSrvMF4VaepD2CimEQjX/h+c8jJL50W21il2RVG'
    b'mYHb3zzg8xbBLcFMtARWcwSA0fzBBd+XbwflnSMY0Un8R7v12TCGRBmho5CKG0onhoihNqspgj4NpDvRyUMQy8jD9+dnb15BUbzr'
    b'XFFIrI3cp3QeviZvd2VHEtMKzh8cmL9XUP5+Afn7BOPvGYe/Xwj+/uH3DxF6/5Bh9w8Qcn+/cPuHCLV/qDD7Bwuxf9jw+ruG1t8x'
    b'pP7u0fScO8A8oqQqrq0fGPuJkDnxyHsa9u5n5H6R/HTv94nlf5g4/geM4X/I+P17x+7fP2z/4SP2Hz5a/+Ei9T9fkP7nCtB/0OB8'
    b'W948XGA+j7t/2KD8B4jH/xVC8e8m8Kj4+QcLxP/8Qfj2pCNh+J8lBN/tPf4691kC8N0hRN70Pmv4PYaVOQF27tiiAfjDg+8Ho0W7'
    b'8F8u9N7njn5j+K8UeO8OrTeY/s5h925PvYH3+wXdu+h7wu73Dbl30UeD7j9/wP3gZTMNGJ8/3N5f40jA/X7B9lHURrj9oFD7KDLP'
    b'rDAwzj6K1Imf/+xB9h6/hsPsP3OI/YCRuEz6WQPs3fH0h9j/quH1w4fnUu1hgusHeV+4R3/o+bJXA6C7cU5qH/swPcBsJz0RHCER'
    b'gfSVoJDfiKZGCKKPGn4YYb39ndkhRZxQZz3E6e1L8HKkI5/b79SRp1KE1ZZBrDvY7UYtmNVi4FrZb9PyAYxYIAr5Poeawu0uiH0O'
    b'DVoLGrG3ABbYXrR/8Jwc7gz6s3Lsl5FjKH7qYjI4H8eenVjXlMHZOIZ2YnkdDU/FEV/3oV5havWNBhJ24EEd6so7psNd9FAu0gOn'
    b'T6wLefm8Uw/OsUSgF5p3SN1UBnjP+B7yIUA9Aez1fKmg4IvwJuDvl873xTZJ32lXAvVVPzqGmzn1vs3qXwHHAvMl3nqWt8FcVX1O'
    b'BWpgn4TqPh/mTgR/1gvm3PqXMxXnjjN3f4gMS7SI3bcCs7fNN/NeZ234MxllbvMS5eRAc5vLBXGniDC0enh3uIefTG67YT4GcZyx'
    b'x3zrNf4ZtH69bRlvzYCfvVd4n0LcUUXq+Fb2I18b3yRVsYR6AV+yEO2ZhUjXg5PPtnaROPPtn6ouR0ab0ZC8VrEdJ+j2LH+KBuV5'
    b'/dkQXj8i2YLWaGVwFcRW2ZgCoFhFyXwLT3SwHXGu6890pM0OgvugLjtYKuD1cpmkTiRMAMaJ2Nnho7Z8/izfLevmJmkyG1MIynIy'
    b'dLx7ZE4Y+N/riZUHxhFkIrmLcAfiMgBeKEBhKqplDeJH/BM2tOcY55xdA73b5Iafy//Qn3rlcljaSGRauTMmomyEEgrlz0hkYvB0'
    b'SNESNh+NzYLgSJTEvedgtOS+1yg8Nzd7kl/d2W+LKpHCiQgOMG43X32V5UvWrusb6RnRQRQbVsot8ptWqmzISWaKu7ZrLifs8Fuj'
    b'ujlggsi6bJG21+jlAZe5M/Yaj8CkvFBtTMc5fSbK/Fiyoa1z8eHbLncKwlIjJeezOfsx6dZqJKRHMdIWZUE7Nl4ph3VrQ1hT10Cu'
    b'LjBkXgHd+OWPt90a1r5owQ1JqsTyn+wRg6QhZ6xYVXWTa30YVwYWeZwtbbdFZwlVA45xnC3FWPxJ3B15sWTZ0r1PqYUDR7HxaIyf'
    b'J44XOF3XmzfJluBKDgGj1WoMu+HDXBwPopAt52iMsm3PGPiyXHS7bZkrfoZN1E01uyII8OzlJWxQnapuPPp+V5bse+2JgBX54HCM'
    b'OuZM2ePjKRLEOB7Gox/58cGAbuzP0tEGsMU9dALofqq37PExNLeccEKdqyxG0J/7CEI3slZg9BavluxHXg7yu7ztDrd5c/iG5+px'
    b'vWKjj6A28KlTAFs9TcpkOTJ1hfo3PsItmyTlS4GPZvKf/JlL/kslGRlBIVr4X15dFr9h8VfLndqkmKoU+Loqb9lPmEVqGvV/CpDe'
    b'RmQtRI8T1JBlOedODO4CkP4PNsxjl+60UxWRI1HlsfK/vEo8ZuAMkaddTbbAi2zww6KrO8j2RXyWBsSrcpdzv9MgqqzeFFUCvi5N'
    b'us5BeEpm8mE1iApADyO2H3j5S2zPhOwm6BFJAYMYwzqZA6Ynkq4NgNSXigHAmzrptPmpH77L03WF9qIBwOATt4aqxdu8SsruloJJ'
    b'66priqsFRTik9b6NgtS2G2kW2BQfoH1/E58bY232mbw+D+RSRBqRaU0DEs4WGLaUCkiVAT5WX2TMFxnzRcZ8kTHskuvjYPboig6y'
    b'yLzLb6esLDZFN2UiiSIYQ2yN3TJqgFjVoWF4OUXffMQ0Mm4N2ZLNiUupBuCXh+XoP1Tz+Zx9xBF9YvP5fOTCqH7rho3Gwk0ZR2Ne'
    b'U4KXm+jFBmR6Ue1yE42ghI3lXZ5v4S6SIv1STFokKbbk/86WMhOljnkVKKG1f39CGmXLC/h6OUvr7a1xxZU3Ox5Ajos0ETCTr776'
    b'6l9vm7rLUzAbYA6jq11RZmPrX9KwkBUN6nq3E7Q54LtsiXY0w0QABgb2j+wcfWyeY4wj3L1Q1YXbpJ1jn88lXa7YnHX1Il2uAB0f'
    b'/HVSctdrHimpP3BwSBhyu1DGRP15A0mWF1mDZpwleKYnV4IeyGdsDikMOc/pVssyWcEneJ0Bu+wqX+BPPNhFNF8nbX68WMICchuk'
    b'Eb0prJsCJq0zeO6EE0NwCn44eTyg9cmiqxf4X4/x4mgieDKg/ROuDRXVSrRsE+6MJ+bEpwQ3JjA/421lV1Uc3Jynab1ic0YVAJaQ'
    b'aeK8RiAeYOiIuRYfbfmwCng+4fmXxkh2mpJTvQT8yZcYKWEL2h6zOUObG6xuO6ZaoYRB45wTODn6EaDZMeR92KHEkDNhMDQmlCs9'
    b'q9lsZgiHEO3J2XHrN+S0+zhCmq4Lntj9WATgqt8wagnuyEb48JmmjojLtc0tSAZ0dvf65uxjsPr+Q4dnwDLvHmj0fE/miXCbBUXc'
    b'ZkPrG2dGG9ypIUsg5HxZv2Nz/g4RBGm7pNuR9UE+PRSfe3t+aggMzus+NQhWDw+fzZ2PZFghhx37fU1hipo3gpTEp5XwKEQAHpja'
    b'pHHPsefSmO1DD/alf0UST6rncnsKTAwxcZHJ2nfFdptn7CpPE/i3QQRdpL1oWdsVZclu8uQd00mZ1eRH467bLDZ5Us0/9sz1QEIe'
    b'TKE4xORsdvIbqBhDINVX+GGYbfh+/DLhd33Tzj+i0tTTgdEAsE8mnyYzG7Hy3+lbNUOSnhydHj0mpKm9XLYUtdCDEBDGerG7CX4N'
    b'izHvmcHxewhtSPfCzCV1X9wTEM/IUW8N1M0LjA0ImYhCgDQkWLsWEiUGV9SJgnKdMOyTwiU3VwOtX7Xm1HtUELLNOS16iBQmijwp'
    b'jHj/6BEh4Oq6Jc+HNEnX4NyJYcxSGbRCm0GLMFXCBxD9hro21Uoel/nGvJSwxw/2SIsWRaf9UmNsuSfEdoO37kPx2C3uYa7uYs6c'
    b'ze0+77m9zEnfbWPBGgq+sXKxyt8jkcQ6oYPVMpj69c4pYFVDgn9hkffalM5qdA3Y5gyPBa7D2Xvns62SsX//hS+UIX+Ig8lMRIKQ'
    b'V+CGpRxo1MMQXzwOHb+04Zi+0TloPWFqZ/l3sn6rZzM8zfngHzEuJb5Jzxh/CzxKky3jb3PMzFvHxq9fv2UyhkHkWCzqSow4FE/B'
    b'6eK+v4czNEY17fsElpDCEaYtLsBiCub0NRZHOHoeC7HpSydxH0al8fU5QCEOEgowr+saDnn3Uzi6xdHkw2T1MXCbi1x/2/s6spze'
    b'NjMtOH4v2hA0jWD1K+cIx8qXr75/fcme8XyyBrO6SwuOXEHsXAH2x1Ylm/xgyg7+j4OJ9Mw0/wbvbmt9Y7I5IqPlny8SaLCQzA7L'
    b'btV0sEyZhnHQ7FRgunzgo72awjrIHDLxRQw1dh0hzT8nvRf8hd2BPNdgz8lXOFjQUoVy9o3L/pRIeOudAipzhalYB2UCcRhkZ+yt'
    b'Cphi4BDCW7Ou3h6+UkxuTEX4vAXj2OhTIBT+NRRcOq/T8JEDY1BO5/jJkRknh6ZVL516T5JgCukwuaZx0vhCRR1JXrOu3hrp5Wlx'
    b'5EVZqLGjkKO/dfV2Uc19v2JyCAsg/u9CO1RmtGjn8IDei89PhQHy6uJkyh5fhrqAHGoGV8yvnOgK+LOF+b1khMc/95IR+IZhE6H3'
    b'2h1kOy0dqKBDeuNRUYQDIO+6mwcHZ9IbOdcb2cTEY0PutIcpSk1Jqji/Dtq0gZwGn23TLvRxQm04NxmC1UBstNPYXotuZwt7aCcH'
    b'UXPHGbwu1tmA4TvwgBwArgue3Yond5yykXA86pJ34E9WjsgBPJx8eO6z5b0EhMNDiLFXQlBMrYUDHRhL7+RwjOs+8OBzOgjeDDy9'
    b'y+2yP/64V67IQFn2RCpSY9h1R9yP7Qi9W4+gTMhkjzunv8/pRfA5M7wAQ2HtjPcBWLragPxb2D9NjJtyKMwYbTnmfWpKHNT32WjP'
    b'vHW65z6zZ9K7x+gF1LvM4gFVw9UskNcqiz39OWgo7CVWsLtlUpZA/0CPCwh+4P6U2f7RutZIqchZJ7g3T9q6mucfDPue0DQwx7p4'
    b'BPdyrxtv4A51NKtJ1gqtuZ/k3Vlu/qudAWlALSpbutimWMG330klRTwGbJs62+GZdciRzZxHwaXt9Dn/aAzkgK5ddSCknffAuKRz'
    b'59bvbKwBoAM5TQKvEau+yTdXedOui62HOASlMRuldfG/Ag767mmiWgmPrPmFcJ3XrvLSNV67wmtvXfhNCMBl3RgVp63KqRjmyX29'
    b'/HyMDaSQBoGoWctCJQoMGllH9uYnyUI/4OYVycHRnUtHnHOJ4r2f61GxNTwkrZIOn6O4TDbPLplhoJfSvyK1NcXjLGFJU8eqR0s8'
    b'L/k6t0pKX+xD6MIhbsduim7NPvqlzBXc5BMD21Ur6Wo/EBEUvuvAgyZJRzyLQ+4qIPcNQyNpfXSy8hv+BsaBGBinm65fbwi6vSai'
    b'2zIUq+PgCa1JeCC6HOi+u3mvzWwMQBguhapgeteyOROZXb0gY+sMdpaEH3xgaSVOWjUirGHqfDMf3Zw3OAcywDuqvLnzgW6tN7tq'
    b'p34att5Y2Yn84rSnKrm45Vs48ULmVl0ekHiecXAErdsDi5xxLCHTDtrQewvWBXDIzFEUDmnc6MOhkkRRSOjEJPZ9XU+ENLlEWurh'
    b'k2aZSEtj0OTvLsOQKr1fmo0ec/im5mMIXuMCWERFs6EXPBfLXSrNKRHVe3d6KoShq0ObYs3Xl8xQeBkEv0iWHUSq7ir6nv706kwG'
    b'K8BVncsPWRsF4+k9t95hAffxWWaQzNWanKq4gjHlRp0V7huLzrTGmeq4ew10NXNFc9JirQTz1546KGTBalJa73+YewJ9n/P8Ac/y'
    b'QWJeZIEwCnQZCtKnr7766sX5989+/uGnxfPv/wgv3pzSZnAEj8LAEHweX7FIy2IBRWDGGC9RVB1n2dFo9IYrDyyrd1clFPHpDouK'
    b'XeVL8NLr1kULp+yuhJfGCjMAQIAhSxjEtMOddzYaCcd8nnYgaVbbpGlFngH8TwjKkT/PnjWrHdzWfsQvWmHI8jZtCjQRzJ3L6I/F'
    b'FvyFcjGSGXuBk8IhHG7lx/xDnu7QwlC0MFCs5M6ubp3bn0w487cMrhpwaS/rNCln21sMnoH4xCItOvhyCNyLUThNXbaGlyrfgTL8'
    b'A+YxS7JskYip6eGPDg+TsqxvDvkyHMKIm50ZKAl3mrqaj/hu65qdGT26zsvtfPQ2h1KVemR8if6WJWVbM6H7tewNZkh79sMPr/+8'
    b'ePHyzfnznxbf//zDD29+fjU/mQmcwozZ8KcQPnD8Hxh6q99DQEnUk4BvM5yG5CYxDQ1RZaxuZ3l1XTR1xRXL8Hj4KzlW8d6OJ2w+'
    b'Z6MTTlszvIKPDjNeOezAB8EZUK2+UIv9VZ1CZNa2qa+LLGdXdbd2+SFGOJxZYA39u/+uBMMxdC6TGsnhjY0tK9gGA2yMnC28vVlL'
    b'RoU0ONW3ok0pYxGFRJwGx1999VWxZAt0X1gscDEWKCkWixFfjSYp2py9vW27fHP+oejGvkyZfPX/AwH+jisgfw4A'
)
HISTORICAL_FEATURE_PIPELINE_COMPRESSED_SIZE = 190866
HISTORICAL_FEATURE_PIPELINE_COMPRESSED_SHA256 = '9c7b10553bd8e5aff3777a6a1e31026ea8e44a3b1e6cd54068f4ecbfb61cfc0b'


HISTORICAL_FEATURES_GZIP = (
    b'H4sIAAAAAAAACuS97XLkNrIo+F9PgS3F2Cx3VemjpR5bM+UIuVttd5xudR9J9rlerQ4bIsEqjlgkm2BJKns8sb/uA9zYiH2E/b2v'
    b'cPdNzpNsZOKDAAiyqrrbx3Pv1Q+7iwASiUQCyExkJgaDQXWwv79P/nVJ85qc5bM0Z2Q8Jgmj9bJihOEXVqX5jCyKeJmxyc7O1Tzl'
    b'8hcpHnJOoqrgfMxZVKdFTjPdOioW5bKm8JUEaR4veV2tyB5JlnlMFyyvaUb2dhY0qoohYY91RaOaxSSpigVBvMK6KJ/uh2nO67Re'
    b'CuiTckXiJWJ0wRIa1UVF3s0pZ+R057KmM0aeTsgZjebQDWJEUk5KwCeo6R3j5AWt6cuKLtiIVKxeVrnxiTyk9Zzk7GEnKrLlIud/'
    b'IXlBeBozwpKERTUn7DFiZU3iIuI1oDHO2D3LyAOt8jSf8eFkR+FBSVADraJisUjr4QnRNKhYRuv0nhFeVyyf1XPyhLz98pylGckY'
    b'jVnF52lJnuzw5e1YNxIlexmdzWgVkycGuEJQeUKu5owz8rUeOye0Yjtpfl/csZikOeHsw5LlESO3K3K7TLM4XObpPas4CxdFXs+z'
    b'FakLQusaKPiPwyNJ20NFD1KyitRpdMcq/GfFbmlGAWBMa+COV4uyqGoSpzxKyyzN2c7Y/dshhMgJjoo8SWcwp4QEOEkxremI8DrO'
    b'0tsh1oS/f9f/+rvRes6yklUcm4vW8suI5MtFudoraR5Tvg6M5FeEE3hY34a2Z2K+DnQHA5NgQdOclGnJgESkqKI543WFszg02gM1'
    b'wqjIMgaMPilXRllRsoq2vgL1kyJLi5DXMCPlamenPcwFXZFUzJSx3JrZoHncovFo53ZZk/Ozn84uRKN6zgiOQ9BqsjMYDHawJAyT'
    b'JfQVhqoXmueSSfnOjvz2N17k6t/ApeJfdbpgAgpwFPxSMNTvEdb5pchlvZLW8yy9VdXe0XouCupVCfuE/H6ar0bkVc0qepuxEXlb'
    b'ivnQ6OAkE8pJXqpPYsbhWxk3mH5YMl5z9XuVpDkuAMrJKtkRPVu0UwgEOE00K+c0vKc5bBJhSZechZxFRR7zEVaIaDRnYZbeszBJ'
    b'MyY+vn7101n4/PT5D2fh6et3P5yG7y7OLs8ufjoLX746e/3iUtTKi2pBs/QXFool2gKIPAFbrwEat29AQdAjrIrbJa/DX0Sp2Pag'
    b'rY14xZKK8bnsiLuVM1ozXhv9qfoxXW1SuaRpZcNOeSgGgnD0t3uapbE13KyYudSI0ruQsyplEla+XLAqjeS3sKjCmCV0mdWiuIQ9'
    b'L0x5yHLglVh8telSFQ/hgtFc/OI0YWGSFVRCqItwlYR8tbgtMvHlIc15UaW/sNHOcKe15mwW+e7s/PkPb04v/iW8OHt9eoVT//b1'
    b'j2/O5TQ/f3txFr788fzF6Zuz86vT107pxavLV5fh5dnzq7cX4Xdn52cvXz1/dXrx6kxWePHz+embV8/D12enL84u7MZCBniOSIkv'
    b'0E94dfUmfHn6+vV3p8//xW7w+vTq7PIqfHv++ufw8tX35y42b06fX7wNL86+f/XGGQUM8OwqPH1x+u7q9OrV23On+O3pVfju4u1/'
    b'+dn+/u6H08uzY4X869Pvvz+9eOGp8k34/Gl49ePF+enFWxiCXePV69enF+ElUtIqkZhevPXhdHn6/Zki7JvTd+Ljzy/DV+cvfry8'
    b'uvg5vHobfv/q+WX4/cXbH5vif/3x9OLq7OI1jqRpiGgeHoSXVz+/PvOS6PLseXj206sXZ+fPnZKzq5fhD29fv3h1/v2lp8pwZ2dn'
    b'l0w/x9/OLnmlBA2fXBgoaWdEDvcPn433j8aH+8PP2LspzShJZhPpBY4nJb3sNsLSgtUUjlXyRIth414xjNc0ujvZ2d3Zhd0bYYcK'
    b'WqigYSEh428JjeOmWPUQqh6aekI6ZmGRszQLm/5CHhUVs+Hx5W0DU1QNpRwY8nSW04x3ISBPXVkNR7GgJexOuk5dhLOqWJYgKFMU'
    b'lcdZUdwtSylOkYhmGYuV2F3PATtJZF6zckJIGDPYDEMQn9NcggMhQvwTd0ropyoeQCIlZZXe0xrgGEoCzZT8RpZcTHI/MSc7OzFL'
    b'OsejdY4TOPuHQBteVye4fgaDwcsiiwltzm/NIUKuJ2leF8hEUUErzggs7DGvVxkjt8vojtUISGH6vnMbeD8h5EIqGl++rees+pIU'
    b'OVmknJM9ck7PJwojcaYlDSYpJ+dFzgTKeOogHDJAMKI+J1PAWA92OAH8y0CIkWlC8qImnBQV4ZOseGBVMARF4NdBTvPBiAzyImeD'
    b'33q7WJbABVPCJ/gvCTopKpLRW5aNyB1bwdrs3gob8BIhaNF8RDGkyOs0XzL9EeDfAdR23TQRJYiOXWQMAZHb8YxJsE3XUhZnsNxP'
    b'TkgZTxqNUdDUbOFWQDYzP2l+e8OqGUOGarHcWG9KKOKQAliPKhyI2uQE2VFPhbUVswp0SIAoNuQxKqrvFdT3WEv/FIviPZGa3GQH'
    b'wY3N+urvZErKiiWsqljsWSBxysuMrkYkoVkGS+WWRnetWTD/5Eqq6EMD5Y6tRvA1J1/+mN/lxUP+5cRFSeGMKHWtQ9RGervvW5yq'
    b'S768dQhxMiU0SyknRWISiRckBrtHXTG6IFERwxTQmsCeyXvRAI5mKfAgyWESAzaZTch7dRJwkKtBDi9gd79lGX/f6Je+vzvGSk4e'
    b'iuouzWetXURxj9xEYAeQnyZsUdar1pKXpe4uhGxuQrEKXFjFsiZT3VFUlCu5XSgCRLBwg4ECAluQPdvwxZiMwbC19iPcQtIcOptI'
    b'dm7vAsWyvo5uyJQMJHsN3AEXS7GHR0XGQyAmmZLryMRS6BWAkXHAOD9DWA7utzumqokJtX5g6VCMJM0desrx3IhdCEg/tWtca3Rv'
    b'JH0ncVWUYbwsszQCVcrAG6pNBxnl9UBMgz0/C9iTAoA6IkU+bdrNi4fpIGOJapYmzTQNPOQHvgCCN5VuJinPaTCc0CwLjDl0apGp'
    b'VHqM8smM1UGbxPZimCRpluU08NUfDDevKybDX19zjlNMeb0qWcDrqikQ/2IZZ31jdWkkO/ofiQLD1vBxUOaS9Yy0qeisdh9VFrQM'
    b'uqS6oUZNnOZtdIzV/Tm1IKlLTI4aQ660/bbNuYFQI8Qx9fmUIRBbfKK24J848Ukr9zRbMrAhngB64psQymEfOSFZyutrXlc3oqhY'
    b'1k7lheol5OkvDAYPO8hRn6hzubxFaz4e+gLRsdAJAHVhPXyvERNyykOV1gwEhfcShfdSQnlJs4yjiAGlv7CqIEFF8RSt5zQHCXpI'
    b'HkCOaPXG6aLMGJxddVEIaXlBswzg3II8k4CFCGfuP/7P/4ugsZ7eF2nMCS+XVVoswdxfV2zByMWloCSH40HSJaqKsRBBOMnSO6YE'
    b'THGLUD8UZMEWt2A9dc9mPXa1lcZJ+yCLk2tJClgj+5N99/yKEzXDoASU8aQuQmnaCuLkWndyMyKsqoqKTwdRwaqIydU8q+DEi5MJ'
    b'Uut2FTR8MSJwpuR0+pJmnInqMHfQ0awqDdiTuqI5B0oGGV3cxpQ8nji4PLb7nwCwQG46UbHM617IA6wi0RYLgMVwdODYxwK14eRh'
    b'zioWSHDfwrlZBzb7DkdASAnHoq9DPtmHB3O5/WgwzWQIvaKt8v5uy7N7BX5XFTSOKO9agiDSGgtQrS4GOn1VPEwI+ZGzZCnUJxCI'
    b'6qIcg9jbiAFkUYCxdrkYEGmDIIEyN4wMA8pw8k/H+IqTAYBm/us4AXlRS3/NLNwMTVaExoP1HIR9fAT79Js8Aq9e2s0Hp3HcnFa4'
    b'z+pfOD7nBGssYfq2SGzC76oiXkZMT9KYvK94g+evB4vR08Xo2WJ0cLj4zVAkFespJbK5zry49IMSZG8D1KCEGig3XgtMIyYXC7H+'
    b'fm0hdSL4X/EuLARYIaqpB5hczj6QHcAM85AN6rZiNK7nIb0t7lm4oIf7+4pWJ6DYi/vqwrAAYU3y5vRwf78TNS/UEzj8mOBmoTcb'
    b'WH1GLXGgb4DhspJp3aDRAJ3F7QHTqTOu0zr6JG1b6zMhScFzc3iGpKpNSFBpDhc6RY57BKiOunUwAHY5WIDWZ/J2+4uYwYPFYDhy'
    b'Wj9t1X3a0fqpp/WzVt1nHa2feVofHLZRP+zC/VADEEI+sByvohEwMZBmBMc6bvlpbpHMNRp0S7ZGvZGAfe3ynWFGGNwYfdvH//TI'
    b'0dc+f++KWfSwWzh8beCA/2xuWOR2rDcUcVAF+vBV56s6cYcTm+Q4gqjIYJKMXyDopXmLQQVDtXdN57uzAXazWxvSs15IPazXBuUW'
    b'OLBMNmwxVlsi25yTTJIOPxfghknMOZLsAHtVWaURM3f0Qd9W5UelxbzWB08XdoU1hLGB9R1xBtzhH4q1pnoH7p3HaWsEPWYeb3tX'
    b'jvUcL2vb/c5mjeMT390n3EU2zntjUUQqmt+Rr4SErI0en9fM0X89uq0YLEa29+q7F/LmwB1jM5lGiWF4ldu3ko6/ksJo61YWKCNW'
    b'8dWckSSteE2kl2JES5Sopd9UVBWkpmn2kOYxCQa3S7h4LKI7vEjjdVXks0YZ5IPhX7Cd8BSyYUm5WMuMJYvgQoAUFcyVAA2XtgBt'
    b'9wAkvN1DcQGRgs2E1rI70dVgOCHkebG4TcGfERouCF9WCY1kd9BS3HNg21uWsySVfmS3RT3XnpJgU+FskQLGSySBpK26SaYkmqel'
    b'MAGsInDKqtgML4LHt8BhrerwFVwuYR44JxWLintWrUaE1dFnv//4X1my3SXfW2v7BNbjLbgqLlicLhfjmlULR5W0pRbkSglL7myo'
    b'fhbLirDHlNd4b8jyaL6g1R25uBTzBzLToli0tGltt+6VJdZr2wBfobNpH76NedO+9I4xJYEa2xOyPznax/1TA2+3CH8RBrHG20EZ'
    b'KnAGHea0TBTNXqYNcsEjGZNHZXUjeyR4nPA6DuK4SKb7Q/KEHLDx1wKL9kh8x5XGE/dPZCEbfcVJ/+ZsT8YZciJOklu0JYXPFsLv'
    b'lIeaL8JnC8EXaFiDylI+D5QRTO35l+jKZ/kZGFamzotCuWY1ABgzag/scQqN8F8jEsMNwxQd/BoRpm17wivHbrOToAeMIiijenpV'
    b'LdlQ+6Bf708mBzd/IQ+MPIA3vtr8aE2eHCBhpMcPfhofCLrgGGh+h14gjSnLyyIjdy+5GU4QGYsiCrMRoTxieZzmM/l7wep5EU8H'
    b'9J5VdMaa69RmdJKcgUDpK3I42SdjcjDZt3kK6xsnplzy1gQrvWLYqlzxVl2HZzyN4KbcbcVKDsz8UM/DVbEa+HhdHvMGJOfKUi5l'
    b'dzB6jTuIw/dD9zsrxXnqIdIueZmCY1SHaDYh5M0yq8HTHiInimoB7glUHehyqaW5hEXJA6N3Um6DKI4lBFzAOc0eaVRnK/IAR7ro'
    b'7EtOnp+ek8vXr96QwesByZgQSHbBAE/zmE8I+TcG9kroEO9VaByneJ2SZAWopAWhuQyYEP5dpiFaApM48jrNMsLnxQMngFxOKMnZ'
    b'sq4o3KLJTRTbCcZfyGFH4v7G3XwmUZaWAfo7TceHk+OR8BWaHk6Oh+SrDSYZO1HjAdfeAjyg9idP9zdvjtX8AqzgImcQT5wOh9Yo'
    b'nsLOJEbx1DEe/z46wfEJ6QtAARftxvKPzqzhxdvTF29O35H//v8AoSefVSPY0BFyrfuW/z7zmbx6oWVYz8HDvMjiE+BjCqX7k6/7'
    b'blvEESduTwJ728XDxDg3hyNb4TDNuXJAM1q+PxFGnw9LWtVpBmIXzfGeK05pDuc3r+PmBHhNwbVsRkFliTJGlaRNOCupiCr5i1yi'
    b'otK8WBQzljO44TQWlRed2yJfcsG1709IWXCxxBXvskrfDylsNV6oKpB/++Hs3KECbD6ofDDpXDinWUIKca0Df+97pY335PT8BbaG'
    b'4cAGw2JO3luT9947JMkrJctpVq/0qBYpnNckZzPqGZzG6rao62LRzIoYnxwI2ttNTUpenaAkzcWdcMIe1LX1e5sP30tg4B3L79Ky'
    b'ZDFheZ1WTKoSAV5czysGDqnC54azGi7t9if7OAUV7J1KpZO+Eo0uat0BliCV5DgG2K9AFq/YkjNu0Kq9rb1XiIDMulIqekyWpXSG'
    b'S/PGm82/770HtycEU1aMs7wegV6WWFf8lGCIR7YaQ6csxo6A7RhcjUhJ8YnY/+xzH04cmAoz9E+EbQBccGMeC6U4mtN8BpdbcgHL'
    b'zfTDMgWPR9OUv96c1DZKOqKxaRzfJS9YwnKe3rMT5bQASC5zySHSHAM+lhh7QnixaGYc4rZupSaPHsTg+Ce9i9E1YgwSBJJMNACY'
    b'oIRWNIW6tvOihIMujOL8TdI8Flo+eywZhmPyaM4WVFBKOu+CR1fkUYWbu1NFSsPvS9xE4SVAbwiHLZ/LHq6774KVut2vb++Sgwn5'
    b'HtaLuxQMdWRC3qHXqySAVFLF4P4iwcBIYCVqZs1JkY/rORsn2UqoM2B7kFPT1tA9wkKngmJU8qoa/SJIhxJimy57dW1t2Qd5dAOF'
    b'V6zIbniulL4V4GYTADZ4BmKYJWhXvINutnqjwVhft9OclNXE9Dy7cfznLC2vrTu52pXTerHMgkNz9PiVL28D0KUcxQtxC8vjlpZi'
    b'/PZpFocT8o5VylWqpjUnwndmRFqyx0iKHhiaOyR10SwHueHjopGLaUalQAFCOQYHTMnHU7YxjaS/wOz7x2s4MYk+LacNaCoXwC65'
    b'ckcn7/HBmChOUXQksvjo2yl5sj85lhACnoJHvFjueOhejw9G5MnBzYh8O4WK6HQ2B4e2kqi+5G1dXZThh3BBOXJnx+x9C1x+rJ0b'
    b'DdODaM6Xi57WXxmdDNdQZqnUZdEEOYBMDQAbtDcVFc2hEgJQdmpgvWd21Bj9kL0+cnZF48arLeR1/LGMUsf2BmQNjY2fWaYFkDgh'
    b'qGGK4roa7dgYEcjqEiPJO/87eDDCQSUs++Ca2Lgl1tWS1yM095zTc8JiLaU0PYoNVtqrGlm7lO5veqV0OcDZuJtjlRtyY0Rz7GC6'
    b'wLCHiY8WmfYbTfVosj+EQQPaKQczXpqnwhiQrUhe5GMlc4/gUkPcZNOE1dp+bmwODeLm9jajpdrRnk7IJQrgclOb0ZqdkCLPVnAV'
    b'wwiqMntS+G98RpVK0uxpPt2E9Ep5JIAVOwTFpAFjb4laUcF9QekpaqO07pf6T3u/AXaDc1RoJ1IFQ4u01SvuOfu+PQd4Rao2UxIY'
    b'rPjtVOjIgaV7DX0wwLsJLTUWFl8ZsNU0Hk3Ia0E1nLAT+zhSao6EJ1fRjNUQvCi102YKxOSUVQHx1cIIBd6/cE9lzA5u5KZO2YQY'
    b'NjsZBC9+zIZ9W9RrW/91SsYdzXfJuQhk5wI1jEu83h+RgxvAeyacvAyNNSpAvl+iBmTOnr6IMOZvD0y0XYsXd3I5hHwJh3iz3Ujq'
    b'q4MGRvcVCaRg1rHx9vRCev+aGxNjJPKyQiiTckl7MWzovw2G44MGRbEqbnnwyYh6NzTDwoIbG/7uOoN8lHOg+owcCFh+2RS0go3x'
    b'RYFUT6YeujVbTzrLUeUlaV5mNGKGcPs7+y88O2ni1B03KRJUqP2O4Y56LIw4ajdPGf+8jgt94dfbui1otzBnQGA6SKO5MQa0G4mR'
    b'4VV5HpO8eJD7bsQySBWDtgJyBbbCWhxCS86qLzlRHgLKvgXCCcwVrYplLsSW5q4aTP+0xgRC4k44zWdKnwzosNtx9uniPRHz0ATM'
    b'yLjQW/BWZxUBxZDVQtUmJLgdivhrNNbAlv9U3i0H6YRN3CicZpxFPtQwoqG+foYhqWhV6Vh7vP+nP8pvAOB2Xdx/souBPDh+lIHD'
    b'Y9tNmdbS0V8nb4IrIIxkp5wMhH8KzMRA3rXgD5zJp2vMBegc2BZElMitB+JVBqUk2fK1b8kxBkLP1tsvfmeEGhVmDX16HSo3cydY'
    b'N+JP8I6QLKP30FuGO4b0VgJ6Q9aCpwsCWaDgiEEXo5w8W5D/+K//TZhsm41X3SjoDfDpAo8Mww8CaDW2eUueRiAJ7YMuciyHHtE6'
    b'moeoweB+PiWBCeVbBwr5ounk2YL81eaXlnDqjFxuJ2rXkE5GuKvae8Z/pi+JaqdcnjQJFAJC/NzXY1ff/4qXV/vrBm3tnidwD1vV'
    b'wsnH3jpgO1lyywsIKjQEQTitWW5mwzfFFqf4btddLtox5S28kdVdW0V40+4wj1XhACq4tDXEtV1yWcN5V8UgfdsJ7+Rdg2RJkecP'
    b'bttuMzzXCoxQ/GWM0pfU4fU4wLdHZ+37Z/HrcYQVlBgbjLe6i/584t0pZB0jP4msY+RJk40C02UkrI7m4CXzxMoqCYJ3rEOYdnZ1'
    b'kqLb3ytJ0aGZpUhtGCeQlGfsDOGHq6t3eBUFSFeMl0UOrEUrlIyeEJ0FjfCclnxe1DK3zxPy9qezi59enf0b2SNMppskjNfpAoL+'
    b'yR5RnLlHIsrn4yQrHkjFQPFFEOOGeJAMzqQY4IIKNquyVYMCfAZ9Hq5EgK81JmkOqUYqgrwpwpZkF68xl9u4GYXI5UZuqzTGIwMz'
    b'nMSQ2spGAP0FETzSa6zopakg7DXQDukLZTNaym5fds2+lYX0CcGEB0KFVnIeJlQRUCC/F7jYoq8qZOAglMNiwIGgg+vPL908QVyE'
    b'7WUFjUWCujiExIZhmoQ0XwWQnPAEcxKimB+nEYZzjiAlkQxUgAxFjcktwXyGE7x+4mbiBPgr6Qo6IlNMnjiBf3PsYgJ7WFizxzpg'
    b'eVTgvcJgWSfjr93IfuXxJiFBog8OCSqBLwL5dYR4DvGuiPz6m7g3EnlPz5Q3T0solfWaX4Iwc8pDedcLyfqWLHhs8jHdFkUmAKUJ'
    b'eezMd4RByKqage4jXEdUQ1R3HlXeIzKdksGgB4ZFb1kKgncZi5QVj8PNBgyqrRwkDrC6Z4oDkpRlsTTO3lLOTpyJNxIzxv4yAeFE'
    b'J6yUMcCdTCTUACgJoEMr+5Pspyv9CZiPsDtQPWS/Jj8CiPYsKgkHGwzFHLRria7NijZDwwmEBXDYiMryd9tmAIRuckSqfSHETgXf'
    b'BuqjS1OH2WR1OU32fT+9D3m9qEPKOau5EfmhS7KU3qZZWqfMW8zntPKXVOye5cv+srCuF77yGWbpLKsiSeuuOkUZpnlULFhXhZzV'
    b'a2oUUdJVFNGSPXYVysNDXOpYHg9yCmEvbLOHmi+Lkyx+tKcK8hqa0SFwxAFKeAEeRstFCJfzoOCLtYeilc8JDMGF4HJjhtLXyzJj'
    b'1/pyZdTcs8hVhkeqKaDaUj92d93A7nMEThMDCR1vrlR+XQ234Oa6Jy8nOdzCipsZ0aTLR1lqDpDLtK5BaQTsJ1WBObuCIxGXWLIq'
    b'LWI+PRpO+HKhUrtJIsp2H9c92BP0dFhQDB/rfhAwoeAzMiXJ4NeGWr/hTCMHaauNqiotKBYx0dSiOBT7GnjrtXZIRbuRPRihsHwI'
    b'0/ixpfgJFnB66+KDCC9xfQDkcLoaYt9g6D0iU/FjwudpUgdH8qKHLlj4ARbbfbgCf8Ap9KXryJvCBsqEfRC/pLCADWmeL1HZhqZG'
    b'C6h8NBxOElAngqGEeiD1uA9H6mrbqEy+QCB5UUNKqBaPTbIiupYN8SBY2p8E5FUd26BBEgiuD0bkcESe3jidkC/MURhfXdr0Y6U6'
    b'RfO5Ac8ue6JRbr6N2z1ZFaTay/gyg6Nb8ZqktP4psRtZqBkrTFJE1xdZt8gXErI1OouLERsNAsZ3YEcaCgAt3hdWbisZNO7eUv0R'
    b'+ykRuY/lD1qmcNPeBGz4JBjIVmFpSqfvXqGiNCEvaIrOVTVoLou0JsHh8V5MV0M0PaULvGqvGUlomo0gY3/F6mql844sK+Diwbyu'
    b'S36yt/fw8DBB/CX6k6jY+7Bk1UrUBh1+AULBr80xpwY3ONFqnnEIirEOTuSgzeOxTCG51omigCj6zSOGgq4tM4vjYbisspFEZSr+'
    b'J9KeF8t6+sz0t5qAax8Lk6LCBNpL85KqUReqCSgMRlGv3A+ynPomzFjnRc0GQ9hIrc+vVAqlIh+4ot2Cw2Xx1lAsGFkxC5LB9b+d'
    b'XpzfOHp0jDwh2KECc7YIgCC/ikn4TYQfgietuHGATPXwr9OfhPY9cbqytZjfW1MSq2iVhKhXQwZyvFsI6jtUjkaQnbRq5JOOKyKb'
    b'hdAPZcZqaBrUdwaMEapVG6o1ZjeSYVwNFQgIeAcVfXBmXWBR0Yfg47tLE5EptEMb9Lcw5qaiDyP7hq0FAxxf7HBMT3shrvgb10WI'
    b'hoNgOLnqAgG5m4b96AMBu5ojZ/U3v67og/Q89BNH8JnxLgCym5R3AjclVQebpQmJE/M+LE46rsI8UyMV08Qkt5k40lS+KoY+jtUg'
    b'fAJu1eFg1Hy6/nc6/mV//M2NLoKsx5FOd6ySGw/Vl0ForHDtmWx03VZSDD0TVAmI3lZymaRZi2TgtpTHKRhrzWxdSEmUZKXioPo3'
    b'alsrqisXVl+eq6hPv5CAMcWVlAEmoIQ569UYvXDkwQaoClh8JST/hjoLCo8ZhMI6KNjKQxvIIpw+9p/7gkGawzYZ/Cqa/Sahc6lV'
    b'nkgkRn1Vpfa9UV2hQdhVxRYOR2b3otErNu5YBsqygtaNruGAxAX+eRnLg1gSu6OBHBS06GRMjYN8rgL+rgfKGEHkv+BNkhh+Ck+p'
    b'Ijf/rfuRPn19KAnafQRGouGIiH9ofOQVnQRrIuBbm5L7pBk6NM3Q/k1tE8YbaHCPeSfL6Uq3y1U3s+lanGXZBtXAMLO+FnSJN3S/'
    b'F88K3RHx6FH74059Xe9yHsarKxqz2PgQs6ym8JsuxHrwbIj+/dDE0NwRN9oQReN1WyLcCUo9H4zqOsWXkR36emCwHYzD+BkCZfAb'
    b'e6zh/zHjUZWiBISfofimPU5xGqVJ02mDWv2IB+m1LtLZgwd2EtwJnc2CARlM/lak+YjQx5RPD/BUVGekhgkcJRXI+rHGKpCHn6Y5'
    b'DypwC/p7uawi8LD6O40gpAdP5Bl7lGENdoJQnBtg+G6QUPx3TjP2d0hoXPBeeHaoioGrZIBvyb63X1n8V7K/Y15zuovbtwGvZZBm'
    b'2QuDGq0D2UDq7RJL4UrteNdJG5tDLQdcMLYA6oEJiGtBNluJi6Dp9ec0sihk7Gzojah/+qubWxyeB81vfwNjs4P6zU9hr1yudAwC'
    b'zI4iqEJf8Ic5gBbyYo+80eNvQO6RBX0MjEkfkYNhxzGDd8uQglo8xWXcVQYiTfpGYo1KqX4iX82Tuj+wKUjTbfUKi1bJ5AqrB+ZL'
    b'UrJfY94ghTEstLsJ/gvU33U6qGwCOqgmXlJUD8JjVMygfs0qgNpCSZd13p2pC0VsWbKZQW5vw5LNLrCG2a6uaApm6N4uVSW3T0wB'
    b'Vhch7CO8p2Ood1VcQq0rCerg8A1c+3ILoJQ9IlriXHdDFBWf09IeC3pUCkcr7LNnRFj1DaP5O6zoBQNhI5sCgrptUODJslgwcNSE'
    b'wwid1jpB2ZUBNwuW8jSQmTK64aiK34t6Nj54ubUWhKzngSCuvxa0mqV5z5RjtTeyltlePJYIDLcWhq7qgyN2ibDIQ4hwrVdrGEZU'
    b'f5ufYWULUlIxuC7mc7zD6gcDdZ/LqhaQaFlVcJsmlkQ/EFnX5ZbJsgR1NOjQ6XwmKox4Np60VEoBeLLZJZ/cz2JZL2kGm6/VSfO5'
    b'twevftA9olbdwdAktgAfh1SIDuo5ysmyjvLiIRhOUl4IQ2YA33nJoulAPu04WHPICL8cdY2arZrHENunjddV/CUAMnx4BMSUZqY3'
    b'D7qwmA9WgjcNOlLxZVlmWEtbzT/uVNrW3ifIUjxweWVfxpMrIF5NF+XIOFiRm29ujJMLU0LJZ4MDuIQeCZ+dhlC29RBEu3pRm3Ys'
    b'uJFGa6loPkB2GAj7N3wSqpJr4cRx2JalIkN3PZG6b9GRayoGgcAcX6DaDSf1L2FWRKi6BWirBXQVdv42oEb8IpHthKrvjz3FrmYU'
    b'1+pWFOejbSYqHvh1XMs5MEuABnCVqK6ykQaoJLahLCjmtph6H0bEnQpfM5PQHOcliamEASOX/zQQBxTb3cLfPd5mInJw96X6GOn5'
    b'E+qXp8MylvrAPc082qJLoWuBVSOBQrOd9qrS7FvfTZqlLz00JE+KX4N1q6uknG/agfIw5XPGoAv5+7P2oU62ERmof24GX6lhMKM2'
    b'H/ZtICwqIDPalFw3SajjeiTdmZAni6pmcQAgJ2nNFjwwL6wqFqG0LtwhBifYeAAexWXNxG/yRK0jtFwE8JLt9Oh4aF4YReoMUu4q'
    b'RhEgOAG+yOOgYpEoixOxJxg3AqJmkyYS/W4GPW8lyBp4JjW/jHg194kBcejYV7jgUnmfsgfztNnw4lZc+bRvhAfKX3UAV5f4QK8C'
    b'aLmnQXvw0LgU16h6LdOH9s1ZW50yR2jY8px6tsuSoe+cmMISXOwg5i8NZcdu2ig8/pbvzr5X2o7d0NR4upr6Wzr6TkdjQ9lBMFdX'
    b'b1qQ2D2AYbdpHdMOOGc/XRVn3726enHqwQOdz4QA3YkG1BGScwuAK4R3wHhrC+C+gbhieAekC0v89gFqNixHz8GMgH6o/6ranFka'
    b'z89vf+4Bb6tAm0C/MJWhFnBDGD3ZVhRVVuPu3UATQ7uXf8594ez04lw8XHx59eoNPCC9fofYeCvQXkuaouLLmRrJYESub9AJQZ4V'
    b'jdBsNNIfu9t1WngU6hpGg/yHffBeUt+v9xuJQyjbJZI8/BDmYDh2dLkP+1LTlijFZ+8uTfdupWtvA0JymQlmnnIYmK+30/uZ8N/w'
    b'o9IeTMXuUw42iLIqHlcuNtBTk/QeTHJiroYQznRw4qdNsjpw4YhW1/s3W9BnCzAOjdqoHnaietjRx8F2qG4MxkD191Vc7WUto0yk'
    b'SwQsV9epHZ577VNhJQRjCeL7sLDiulwjhG4jF6PcKcyKAqJ0wwCmxa1EfN3Ec8Enm2HjRjZLUh7R7AWt2RnmcuoV01qVm0ej1JQE'
    b'/no9t1qIZJxMQLwVt6c8aEMw000ZFyxaMJyAVzb4hsfsMYBofxm3L08I63YXjAhywj/WG2JzhxLpdoBf0PU6TiYpKG9y5/xUvwp7'
    b'VcHLZ8B6kaN2rtcAXReKXt+JMMMgKU1RyVZ9z8R5ySqL4GbDeJYRD8FbeUN/glEPZCrCX6Sb+yYzAf/GO5JkSP4q++iZHOmiYmhf'
    b'4QhnTJB/zmgscosNQfmqQAszb9XETBjw1s7tJvO71RxvNs/N3bDRgVbr9MTb1+dQxXNbDgYpfc2I91mbUDpNjNnV9UT+75bKJ+//'
    b'1G2Z9DosVl0c+LnXs81Fx33jEhiBxaRntxGMdDA08VIe6ylmaO5tjTvH0cnxTbu9mHp0nhaYCDdV+Qmhiy+inynZ792rTPLLke3J'
    b'tiIfeo/w3Y5xEjuDKYGLVW5I4eJLSZcc3xCHo9tMX3xwvDZ2rOOqUuX8FH2pY1Ti0ulEIm1YnSrAq/Pnb9+chZdXp1dnb87Or7oU'
    b'AJRTeMYYPAj8KILXA2uUMmmZCnYRlq3Ofr87fX16/vwsvPzh7OxzdQr2re4en59e/hC+fP3WawUxafWh1d6WqhqSjnQ0C2iJWGdg'
    b'j38dLINO3cBwXOsgqcH7wcjFIFTf1jN5g7qoaaZEVkO5lS1eVsXieZGjdRFSbD9f8rpYsOrsMcqWIMuccs44Z/EVfdyi+au8s7k4'
    b'vqKCNx4/DVj4/DbxoCsKvi+KmF8W4M7mLTrN40uwsUWsoxbabixExK2nwkTcbgoLi8owryP+dCVtZHklDMcj4n56XXAu2xsBgRpA'
    b'zmrZVPYRJR7o+jrSMPACwaXxBi7PJDExbFADiGiZ1jQ7e4QDM8X4fHRBpCu8onpZVM9FjVeLsiruxcWVSsePIZkNLGQfmERdwwjN'
    b'dKq9NoM2SevbOavfpHlRpfXqVV6zinFFYumt1gygWCyK/BKearrEorfLGjQOKWe3y19xvmTxQMb7yINXsmjvgaX2hZG1goYmGGCc'
    b'DWFoprYAIEttCKHhxo4jU0DTN1JCtLEH7C8E3Axhy8HNIdnYHLy9w4hwxR4J209SIM4yr6cyeA4ptQUoTVkNZ9SIaEYCNEG/LQA3'
    b'BHcwNCivgTqUNUjilKjhGQQ3MTNpOda0kNYEM8B401HYe5QzEjsieVOQzrblwJQxzP3AxOE20rubywMq2HkzKM0m18MDStZSd0Sa'
    b'/M21hS8C/aRncerzfmRujoaduDNwfUOo7obaBVo7L28E1dhTuwDqWPkTZ/131EdGLRJVq2kGBR1tzJj6pgF+7Wihebl3pF283zXW'
    b'hp03BOvwfxfcIkp6AbproAuOuFE8AYYO1kNr1sIQbXd649myKVr3XF94L49gUoITc+fajElkO7XHbcAlsoXeL9exiaxv/V7LBLKR'
    b'/aF7ilUf4l99U6jGq/7dT1bjqiqkEfhbDU76bAcd4kpHJ57rti172XAR2JkppE6Meh0YJhQ4TIudN3uU/C0YczjsAv7pt3DwJxTt'
    b'DkM7Zr8oqnAbS0GUzE7IWT5Lc/a8yJN0pqwD9Vz5WaEJANISSSuiZVzotBTgA0MQayucopv+kzSDmNh6jmHK6A+GDfQrGtPuDElq'
    b'4JhCMAS3CjKVj4hCJ5IRmr7MmkGUzIwASgE/xPKgBE5sqrZDKTVy4DfdfY2HKXSS2cSmvTK+fAxQdLmbbmX8aeao4ZtOpJoqltVi'
    b'ale2yoCQEFIpexciixmGBThfq/HAzYX4p0mkNcl5AIIxCWmiaWXbWS3vIj2QyUOV1kykuMLkV/FyUfJAgYAkim7iKwtIt9tRy72p'
    b'Y0bdmYbx7LQQ7kIUR9+F5AY+V2anYmcQmdXa68MKVfjY/aB9DdFxcRe3onsVvdSZ24qc0uFOwidTRvHSquaQxifQu+tAvv1hcEoD'
    b'07hbAwzsHNXt6q0U1ZKrrwee/QXpCmkvkNGt7GNGVKMwcevf0jIK9y2BisLHRdXZA8vxiafBCFOJmbe/AlTn+jYrqiWp3KY0ccXa'
    b'be1PsbRDYOKENfssYing2zutaA25Rbvg4ztb/rA5+SoWGcRFltEqvC+y8HDfjALVkRjw6a6O8MGHjmA5+UYYsIDBg028t8bDzJQA'
    b'Ta6jm1YIoS7puHGFO1+BvvBQg9qe7EEKJVnBvJvtHv6NeUl7Le7rBO/dQGBcqKJ0p4OM8lq/5gQoOZA+Hrf1KPXgIvlFvn3lMaC2'
    b'U6p1pFJrp1DrSo/WlxatMx1adxo0T/ozb9ozR0QGj/rMLHelW7OCYFuVB00SzbNQfORUa8CeXb1LeoC2uH7QLPAGtAqHLAFmHlFD'
    b'6IC/641XiUw/NKkYeFZD9nU9Hg9y8qxRfyJStfkmbkVl/GoXB1+vH9e3ZP/G3BzgT4g9tFqFuAK0ebcTSldLysFzWC4OXelTtzv4'
    b'l8he7viy+zmgLcx4xqduqaXrcU9tyiNV2Qnv7ds+dtb070y23ljands12/uNwSKK9SU+fi8SkTDaPs+sNH6Kh5R4i9KECP814qoh'
    b'lhmTHgdDrBDGS/F4L+PBUFxN48E4nNQF3JVLdpO7IzxbY3lICC9nCykDc/BTl3OwpQqIQofSxQypwrjW3J/sH1ubtsfXqXho7Py6'
    b'VieBG1lwgjl2A91kRGDeJGVHZF48TAcZS9SpAWG9IVS1D4tAnxYtg6ihOQf2CeI3dVr1m7wEjunSqtVk6vRYJK2art3RaOAWWe0s'
    b'26PRyPputWhsj0b15qNV17AoGpWNrzbkKLFgRokzRrT/mSPDD16KiZOyw0bXRzm3oa+4k4Ju41aZn5JuM7ugg6JuI6fEpWyrD/mp'
    b'TeEWBfRHq64Ihkx5XVQrZd3iIb2nKebkMiHYti/ffDkCyiZGQAtMh6CzkZ1PAlIZmLTSZflOSTnYm3kEVK1G3McMiFGRgdVHSRgi'
    b'o7HaYCzbg1HJ1Zzs0xSyV6T5snkwNE10X2uaxteq4k3bvQ2L/KmdmmY9np9yAB0QmuH1wQADkJlAEp3ZjAySugcrjaQkgmrsy6ES'
    b'q+ySMnWFSQcTrFnLjr6zGcL89XfdszbRtTcD284AF6D2FuUp9+04HZM7K5vUuBbZ24j0T+F9FxwL2T4Yxm11C4hvRBuygxihyQuI'
    b'qpFHVXX8qazhIZm4htY5WDWDGBfSn8o5PsbpY5oNGKabWdYxyjom6WOQtcyxAWNszhQWQzjM8FkZQTGBlwE+y7axienP+G0ZYS3v'
    b'zVZ+mLDI2ee5iFH0t2R+7dONOZM2vqz59Csa7xULGCkR/qfftchrkQ5HVCjV4bXrcvOo+BfJghb9cPF22lax1HVvheBFWIUbRM6O'
    b'ukEbURvGWBC2V0tbc12jxijJ1vEGBZSONPlH5PWrn87C56fPfzgLT1+/++E0fHdxdnl28dNZ+PLV2esXlwbQruseUfYZoor+sIsT'
    b'walt5mmv1661KunR8opvX5BwxnLs6oRwJmpilixlHkALNYvDNkDHXIDl+DSxayzQwU8gVKUKlFoKa8RZyBkoXuVVDZSRw4ZfwZuZ'
    b'xmj6oep6ExrHAbQ2rzesESszR1OpMdE4Va9PcHUt6KOYPDWTsli6id6H7dsN14fZatfcbUCgtpoH72xB+IWC/615/aEtOq3ZMWMG'
    b'NXiMG1SQuvIPWhTGbRe4sWdbb4Ut6edfwp5XheyB44Q5kLxT3HlXK594sh4pMpDY+Kmi9Ve2H4l1Ds9wKyawbvjM2YTDAC24dsaA'
    b'0frI7tEGseU3XbFKxpM51plhzCpUTHOCmWJGZCAik/3BSu5Q8dEiX8U2x3XOr+OC2p8TZWMEupFYzwefOFJYKGbrbRjNs7L/2mwR'
    b'4iFe762wvSNhOrA6ZVW4KGJgMmF4dwhroCGlB70xqi5lOvB2C7mNoWHawNZq2WGpTkdia2OoQhjdosdIVU8PDDzb8ha8aF1kwRqR'
    b'C990b/AyLeFa8vKL2pbBe9RGYNr60tJRbAHb1iiKB1vsXJ8qoU8GtKdHDK5DdKsgfU6XTN55BAw3kfEcHD6LNLf+TPCh2yH1VcXD'
    b'7+HSs5V0bRCoydxTPFjMk5I/kcN9JyDQ6al5TL3jmgXtkbDqVLauprx5dV3J4lZmjPaNTJyArl/S6sOSQdRaPecQddNQH5Lm3ZA9'
    b'uHx3F5PQhyey8UCZXX0R4+5DXA2YEN9fDNXrm0FJc0jKtsE7A1cXZ+cvIBXYpe03ALYgeXLiG6/h0Qd5ezpLc9md+ATG9TyFkzeD'
    b'5Izw0QKDB7WAcZjHYcyq9B7aSehpnmQgLzZvoDbdsMeS5pjKguL9AmSoNA3Y+HBjzjIzDBY/bPJUgiNLqymP0jsMjhJJqTDFNIxV'
    b'p6WCh4caomkgitnw+RXAQNx9O74eNvCbYVcOAAR13e66nbtApltRVTzvGjcG225jrMHKIgWGKTThBaN6MBeHMHRtpZMyqkPxZrx6'
    b'DqsNTPNRJ0Sr20mcJgk8caWg7ZLDPCbIP/iS/Yn1gDIpEuu3g4SXC9ci0qCssdHULEqZUmkNOd0l4+/Uhia7OzK7k3dYHpuocxvW'
    b'gUqe+qySTlufe0nFyoxGLNgfyesUa4Lby7/t4iWrdXRA9kieqsexReol0uwK6PkPn/625DWBZcxiInwT7hm+YNuedj5btXEQKwXz'
    b'eZl85lsxEga+IuadrRaUG/3Om/BXc8vtWet9YFBeuMm9f0a7RuJj067BCNu3f7uF6Wo2wwBo9y0Rj5prGuCL5vvH+BFQggrYxHni'
    b'3Pe6vcgoRvReTuIlvuwup7WETPfCKFN6LlRUfmBzdXSNsigX3VPmLjBrvnrW8haT1Sx238Hl0BlG+61GWZEbKDs5ON6QuHeMgcF5'
    b'g0NLqxXoyNScX07ilnVXq5HnThWQcNyclMRyDWXaDWxnR/T75uzi+zNb5PgM4sbvImrcSJEL3WscISuEF61D+aJ1IP/feoxnY0EM'
    b'UqwKGB3CiyzdTvABeUSBdbzxHG5oZsXj/NbPF928YbsqCfoJxKcbi7GNF7DD1AorA2wbP6OwS546p+I1sQ2qmqJXb/WOHcqmgIm4'
    b'dH7jy1vO6mkboPB+M1QTJUO2nez9MmcLYCOwehgEhSYVmQVD9gqf7Updj67Ol/mdNHA0W1F6NyIzwVfmbn2wDw+NFVUtlSDjVhcu'
    b'zGZ23i0Hg6HL5obRLErvHNvOhmtA9O3l8GZ0ag+cSbN2yxqqv8KebXKPxUkwXTeg22KQRnon4zHUUNwF/seNAvdE6Tgk9kfKi8RW'
    b'q2by8lWP3J47hyediD9wWAzBj9GZYrtWlc7mopoDza4Wp5XY+qcDeFIVDMstl9aufSbN5WD9258mhKzkLNT2wvNTXLTW+VuUwip9'
    b'w0XdERGLXGiMVsI4MQXt67WOgwkrbv4W4eZHU8eGggEs2KV5ZslPLljN0K8hUelV+Pb89c/h5avvz09fA1//+Ob8dzmkzB/So1Yi'
    b'2ONPu7OzSy7R5HoYkeBw//DZeP9ofLg/PCER+lZwwXc0C6vidsnr8BfyhIS3KywoKrIo7llM6oJUB/v7+/A4Wwm25nI1cew9HH2P'
    b'sVGIWfe7H5MUsqogwGAweJ5RztNkReDNVpkiri4ITkJCviaXp9+fgfd4XVScLMEDHz+Fl2fPr95eQJJ4uJh5KCrI/V5H8zSfTRC2'
    b'SPbLCSWiR6GPieVNsvSOkS8vi6R+oBX7ckS+vGSLFIx9S+gJPnxH87s0n305IqyO9CsIODhPLEuax0teVysrbGV56/s8SyMe8uVt'
    b'6CtU30DOW5beEkGMNsTWZ+uLuguVbqFilnxxJkZBO6Getm35ABnp50xOsHQLZPXk2tfcdtwxHjOzvxse+E6B75kzu4rhsd8uULaE'
    b'wRcgk5DT8xdEP0fmhD202lSD/4PjQ6RNk8ZaZrWQz5M627v9tJlLPv2MX9xaY0P71fBGFxx8z3JWoR4h1cHE9pbVBISZx/UrHj+Q'
    b'qwmT5DsrzdLIdBMQCHRv9saGV2ugaEewNMc0y/QzzCNCM7j5hTvVtE7F8GCr0aDMzmD/VIit8TRQj74JQslG6OcVWMRrRmqa8d7m'
    b'2Qpyp6SznOCDa9j1itUkEhtVymIiUleI/YY8pLkBYZkb9aZ6YgwKGXs7PsgOvmuI8xdWY5HgV5LY3P5Fs769XeVI4MgJECkSs4QC'
    b'Hn37+S6Zfo6/nV3yGqxfe4TTmmVZWsO/F5B4cI/M8FV2oUIRhn41DA0ugRjK02hEjKF8Rpy+1g+1cxKBixb0CicoSSgedRBMsrjN'
    b'4KltdEcfY3bGtF6RBwZiHDhL7ezKpDBjSG9mDFBphSMxUExujWcj2AJB1c6WnPAFzbKdXcmZY+RCtbS5sBOjJxrutGP00Qck1STt'
    b'7OrTVkhSiLd60hMkl3rOSAYPgfGawEGZNbRWg9/ZRa10rqhPgsNnxyRLc8aHZDwmcEUtCMEEPJQTxlpOQJLt7Cqi8ZpGdyRAPv2K'
    b'YGQbHxFTa47AbSpmecQwD4hI/i0qwvTWc1qTBO7asTe4H7tnDeUIrRXFoQ2QA+/RhPChlL02o/sSlxbGS0AeMaTI71lVS+rDElHQ'
    b'r3N+I0WIkVyDgMc5vRJ34Tn6WE2EbPwOLIbk4Hj8nCTpo7Euvx6eEJrxQmxPB9/8eX+8fzDePyDBj3n6SFhZRHOwbFIOkIUE897R'
    b'afeH7yUC3IAwIg/zNJqTjNE7LoWnZV0uaw4bGPAUAluWvK4YXRBeLKuIwWNCUJnNWEX2cSQywJEI7Z2TgE1mE8KLBYN3oYSuXCxK'
    b'mq9g9jmReRz4cEJeFhW+HWVK9+QJEfGMSEk+IjRf1SCeIaSyYuODb77ZB769LWZLTm5hxeS8rpbIaxPyBihVzxlnMB1Ab16QuHiA'
    b'OowuJEIxIwEsm+eXP4EdF/NxEz6H29PbjIJmDxnAGY1BnASqETyx5ethgtBKuAN5xwji8KQRbnQfecwKG03XGTtQc/fsCNhI2YIx'
    b'v2o703dPcAaYqhXfsIqSBOQRfdXA8VQt4OhCZoS52DOJTzIgERxnEyerjHxVFFD61nmNagDzI3gMzNpipEqlw+0pVDG8XQ/I47Lz'
    b'+USaq2+r5+Ql2QV501w9NAydOU4qIlW0JZauSxAtwCild6P31XXCZh3h3MgCtlDn7cAb1aSZCCBOIyu8aehXwQVg43HfJlBaCcxI'
    b'LDF5PfLkep2tN7mz0jm2WkPgsCaGrjyiQKsFhQfDDMt48govoa9vwJnFkV4lNCMPR3KtsGg0Cp824dUkvCrCturBdqpBSy1Q09Qj'
    b'wooTDydLHU1aPCb1ssyYcE6eTCZda86CZM6nVbDhSmxC70pa16zKyZQM/i50saBiE8YhejG4E/H/d8AajZ6RkDvLiUWC6OnUWi82'
    b'vh0RgRKEXdcN5tYPU0sMuh6jFtMToitWkub5fHnbXL0kEJlNswxMeUH3A41aUnhBXhwYgsI3wxP08UJ5iM5mFeMcxNSXoh8tahLp'
    b'lYPwUK6AnAppyUCY+5L3yooRzcHLTUh7RCELUyOU0VIk/9wjjZsrpCtnM7JH4vQe5Lk4XIFTmhAx4Oh/Qk7Bgeon6eMXzWkqBA+s'
    b'B1LNuZSR3goB9PKHV+/enb1o5P2vhQAZK7ejiN+faFweKCcHf/4TKYtyCeWxjJxhMxFjSo6++dPIwFd+/fPRnybkNAafMU3Bq6s3'
    b'zZizNKmFSxjan25X5HB/fLT/J5AlWFSDsqfanb57hVLTN9/8iVyA/iQUCXAflCNTJic928LmJD31n5BkDpihMwAQF34BSZN5qEku'
    b'jq956JBZztyEnOFO23SQwnMcmdBSk2KZx7ZEY/ne4XOf4AGWpbckXYCshNELwAQh/MPQg18XkMcAJ0qNXzIcqViGPi4glUF5SaM7'
    b'mPKqKGrRu1hwZRHCJzIVwIMQPf3CED2LiuyeBUNwLWO54GH401n40TPcNrHZQPfIoFkcA/iJUVv4L7kk8d9C0VWLpnFl84OV+Hw+'
    b'6HYGkNJ6vUKMsWUsLnu88pW/ILrMa5++tk9445a3XVCM+5aiZeP17CQ+gQ9CZt5iPzS7NmNnwKIh3jLdIHGY+MRUDpsIPR87FThJ'
    b'uvUR2K2TZH+y3xFNbrzMYbe0nIf8MruWCi0nCR1n2PFMc6fdJoghkXi7ke301A24o0QJRf39lo9NP80QfG+k98NpJ7dxkPeB9H3e'
    b'DG2dOEej/jt2I58zczozQOrAo67OOhzZWvmw+7FpZaUwYZlukWshOfk7TDhNPu1+EE2yC7O1mUl7DcMbSTBMCG58+FpAnswg1nic'
    b'LOZrRuUkC3EgSZcdYQGcOrD3rDnomvO45RC2CVJGfQ1OsbCDl+l3x7ks4ht0Y9dvdaP3ytYMbTZwY/j2w6Cb4NZu041fm8J2/4ly'
    b'CF3bq6rZJrlcJOOG4TV4Vm4IXVbsHoizPex5txx7bHzTzvm6zq39ZJOukyhZbU5XUbV3Ept56u1e9e++EttU3ACjVmP/IbamjzU1'
    b'2hPci5Pv5duOJfWfildVMPdENKdil/Qpv+jc0Ki7WjlVem+RRwxs1CSC6xQBD4RrUGgpXlf41NZGp1WaFbxnFNGY8Qm5mjPUnyU0'
    b'pUWTuGA8/xI0HhobuvgeKgN7UhHY8ysBEpbw7clWjYUW9fr4PuVFRe6fYh8TAu8RgQ22nqdcUGBkqr4SGCjAe14lV4yzUYVJkWsF'
    b'G/MB3LIIIpokIFDYLVu+o71D9OEYog9JcHiMhOZ7MV0N4ZIBzM2UPKSxAjaj5UTPFyjIOaPV+GB/31WThXIYJnNNLNANN7GimNYh'
    b's700PGKkgcp76xf+d8mPYDCvGFzL1AWh90WKanWGV1JCUddJKZJ5+JXSuY17aqVQqWEIj0gYhImTtAQ7t9TC5erX6IQkA6ieFcXd'
    b'sgx/jX4bNOZqC46RFDki/9tUj7B5YN4IdjAy7TWYdboGjQhfJkn6yPgUra8DSF1ohlvvkhdVUcKVDdFJDTVB0I4gADgIwF32yYj8'
    b'Q0/ARLeOA3C4ng7w6hwyOWsNr6HGWh1vMBj8gNehMIUYfUkSd6OQ3j63YI9OZ7gg5KUeTIt25DF0ut7NzJmtIvvN2NT0yeYsyQ3O'
    b'EzeI3DlHvBC93zfTU3x9DX278YllJ3t31hA2KBm8tHb2WFcUyuSNc0TzIk8jmskGnzAEgxMGaB3T/YnYis8J+jvK0+jzwdc8BdGd'
    b'EDW0lWA3lNdw1p6xHQiIznA2hkbgvA/rImS3aR3TbRjUbOfhen3ibAYNqqPts83tNiT7w4ZWijbwNez97ux7i7dn4fEK89LFcHg6'
    b'vL5Hjn+WUUFbId1iO+jFYLSPhKFTSeiHvWGWvbkXN9AyOnI2OnPUDb67cEu50YHSJcv+J2CyNl3HH4raukyafxxyhkL6T0Gsxv7y'
    b'z4FOlPxzIGI+lkRnVfj0nwmZ438OjkFcbuHlz38abP7QaXJw+WNnCZ6o+2eYH4XHHzszCouOOXF7KSNQWj/yVHblA/IVOdjfnwjh'
    b'UwmynwZRh3BvKCFtOJCW9N70uOejUbedurGqebJmb2JL9CbbbpkSO4B3lm1rprOAdFsOf2c01mdP+8PwWpP6/I/CrJXC4Y9FZO1G'
    b'/J+JR/dG/J+JhWcjltroS7EJkXd7lyfGpQXZI+qNZmH1/YoEB+QJ8SEm1UdgzDB5iD/yLhd60AMDo8WTj9u1IOXDJMrSMsiKB1ZN'
    b'x/uT4/0RQR/K6SHkg2hmIRTX5et9BZzLe6ex/NeGN/Rdfgdta4+4ZwxUR3uaxJ6TQJ10ehb0oWXNMdgnKWRZqFjCRFApET4YdREi'
    b'wxAaQ/oYBrZGZY6oC+V1IyI/w7qiaQaXmyXGg/WbQizwfbeHay02HZDMGVWZMeK/kenvz0bWbBlLOLAotGeipSfKwNQUMLzwvN8V'
    b'AR2W0WHRSVg+fhY3nhqCeOA1WZ7GDCSRDWQK2WbBKNzyp5EBFq/fATkPG5MxTJrqmOY0W+Ej2eLGRt7iYerz4gGBN+xju+ZpP60B'
    b'3FtBGvUPYc4erWdG7HqwcDapp+Alq4P1wHorNZAON4HUU6lN7R54UbFYsDzGEC9sYlY23jxTDmhSkm6l1DH4DsOYRRzVRrMz7or3'
    b'9gvGzmD6WzcC+VbNWutrq9Yek7bTvr9z5V+w9UzAl10y/vQ/yzr9dTQ5bO7BD/48VKnFxup0wMh1ESUY00XJQFkRF6q7eH9d0Qfi'
    b'4Q5Cb4t7RmYYJXT+04tTskdOf/r+LfzvzQu43v3TEwlFbswq+dWCzeg4oiUfEkrOz74/vXr105lw0Va3yXD/k1bk3d7ZCM46CYfq'
    b'Xt3gwQWLU5pPyHfLmlBydPynsexzLPvUsa675PKHtz++fkHqisYYBkhhSS3S5QJv0kuWQ9Qk3NWm4PhciUjCFGLeKKS41k807JJi'
    b'WaloR4h8pfmdIMTh0ypWCb/SmhOQYMEb/QjC8jBNhKSvOtXTxxPh7+47wqDveTqb46v1eDGmJ0zN9Nn56eurn0mQs5lwoEZiDnFA'
    b'D+BtAL4GDzSvEU+GIgSAFAS+XSqfggcGAW7LLIb65TJP+RyowNJ6ziqBodJmcTIw+BpGuSxJQrl00t4l795evjImNYjmjJY4B5CC'
    b'lEM4MqZNjP8iPBdsJpBAAnCUzzFEAVuSWyaCCHGCWIyQBMey2Cbo1RySKxeZCunelU/gSGaAdGNH+wSugn9hFUY1Cn9zAF2vSCDr'
    b'JcssW2EKPgiclrHYHliHAtacZuC73gDy1cekcof7UD8vIJghnzESZGxGoxW5ZXN6nxbL6nPvBiEmnPs6OgxZjo+8wM8w5epl4GAg'
    b'KxiyTKjZbDAiUiAwAowakFECGYo8iaf7YLbeJEZvhGQGkwrOGBgzhFnodHrtNHHGAd4ZFhrNfT4Kz7MKvT1w0/pY04nemhFq8oB7'
    b'oC/Xo/cA9Thwu1s+wk15qJgPRE7VzV/t7nfJC7VByzjpE6ggFqbA+1vgbMD6WHwFXvurKPrrVJSBKF3Agn5IufScQRzEUrJSPRxs'
    b'6sPeNJb/kqLxP4KgPRNiyWDyv3Yhro+jfYjH258cb9KDv4OjfYSw307BUJbgK1U0m04gST8UqZFh08Qcgzrfpti/ZHGa1zQywlF6'
    b'ZKe89N2+G5M9ajjqKz0uwVblKjAp3dT0+ehc9y812rjjKZHcjiDdAgDYY6VWImPuMaY+Z3ntJK5xpHXz0WJD7vZ+PnSyKXfAMUVz'
    b'7+dDF7xGWjoRNqVtzch+NFC2A2HIKxT3CYXm48Qesm0uHurGmOXG/4yyLZ67scbeUOP2i+cb5f+09wI7Vqj1RBd+1KHM1uc+2vhk'
    b'aPP1Zum4nxW3QPOmPb6hBHgFNs0mOG1D+T8cOZw2TiXh/Ic0UPcPwpSnwQslVviFyAfEWr2oMGljFslXPlyxA6UhQ9h7CpkONlC+'
    b'ejWRNkdvpQd9Fu3SpVyzNzZD2p98vU++spfYEyEkfdWmiugETIz7k+NjrHh0TL7qnR+l5ab3oUi5opkDXk/QAZEqu6rIXSdqdosl'
    b'gKAan93SN8g1pPYkNdZNn/Q3drPFbtywnVN246bghu3pcNzfKma3NerWwgs8ZllNP2aovBZPLq/Cr+3GxgR/tQYVNedlkaXRSk6Z'
    b'ND+CxfwZ2hsbgMN1Uw3Jmooq/QUThHoroThyIE2R42cgWj0zLTAgf8KdEBy2HUul33BBqzyc0TI8iLcgabEIDxbGyA/V+W67tx05'
    b'vvTvzi72wM8N8h0l4IYL5gOQnHDbAPsyUXZT8u5MAkT3Xlje2gzeOGigMJ8VM4JsQe5NX3upB4v8MkrHBHddCDgHV110RMcHdXLG'
    b'IeUAh1R8Aa9pJo3ikEAJugTil6A7YndMHjC74ONfccJpntarcTRn0Z1hFoHXyNwAculynqefHj4XLj765mLXpDLkoGwTFvELtCyr'
    b'9XdQvBu7sLZxw5Nl6obA4T7EU9m8EWdMmb6nqKCKJE2adOkSVd21iDzX3GDl9gngLIEkJnACwusG4gAg+tGbtvsDgutBW+Kz1zEA'
    b'C8dLkcOormgEORqFBQWzIOkrFHwZrayKeBmxuMWlCGeTu7NunwEhDtx/kqO3NChsjoTTPpmvbWt4r3tcqpt7ALILKRowtaOMd4gy'
    b'RnNtRXsLL+/BVGsKY3qd7iQTaAJUhp2DIbzl1IxjRA6HZpiONK0MR+TpkLTxHJGjITnYEz7PYuTNvMiEVlbyw7zIgVZeQbi4/RuL'
    b'VOIgD5jWN8mLcA8onrtt3K8/AspcvZn7d2DA5gfAhzCPZA7wVZaB7TsQlFzTiSb3QPzrI/qh92v6oPcA33pWqXnyoQUVt4PW100C'
    b'xiCnMdrzagY5LWi1MkJKmjie5ggBB+9shQpNK8wMQ2j4X4w8YyLHmDC4wj0aq+BeR52V7ulnxmHtYeZYEsgFNZbJmEWhSEQ7bGKi'
    b'JL6ejKyNvgdS7gSfWOMQsBSYqxtiapT9zQZnp9x3kkA7de0cz+phY7XOhd9LqFIjrksDYWZ/2CjrA26pMhu18epY186qk3NLnGUq'
    b'7vUt3cTsouMZ/FypZ6/gdGpAjjVew0lcT6BeRyPni1otTr1vp8TxKlMsGIon8tacCMs8hg0oNFthB+4JocrlC9jbgsWnr4WJTkeY'
    b'qK48g7WzapvINSkx7Je/PcB85rh/WBjZGnJeTpIFfXRprFTcMby3NrKRMYsMdXm4AVq6pD2FxvOym86h1cQ3gWlig92AjnZ9gbWN'
    b'mo26YBR8APchzWN8ghDomeZC9ZarXiSe5aHxrPeIyAzLOlmq8AEZk4ZMexboVnX1T9P3A5OyCM8P462864FGBFIXhc504wHifOtv'
    b'aLXoqKryVFt1O9K72BD0JilUU/FIhRqsx/qCts5m4RmtBEVhJkSdmEV0FdKkZpXckYVlpavjNv3ERG6tu7YfqNrYimE/krRpM0vK'
    b'2qT+xyjXHWaSNa1sl0Oz2f7kz2Dq2rQ1xINpvf7Z5M/HfQewYOsQ0g+vS8W08YEL+VHlpYhKW9K/cUGDtF7KcclMqgKCs3ktkg2v'
    b'9RZL4EzcEfvgIap8TiFC/FNwFSDayIrvH4OtFyKiqzKlCmw39b7z442wnE4E022NsA+U+C9n0cHTTSfOrOxAk0Ub0tSq7YeEKG8K'
    b'qG+chtvtp2WtsgA1Pz4yQ1VXvIFkeJE2eM3gHfJ1gUxzuG6oQjBAbbyQdIsuZscKt8uVsOhvCVi364BbP+ZbQoQWvunnLAJTxOLp'
    b'0TEMZxOOMut38qiupIeyFeguAph16sd8K5g+EjibvngrQS9ixbvuqWDdjz3RO7v5ubVHN6DFbwu2uY23gdsNHOhqIzD3BQu2see2'
    b'+F20MyfUaGovig7GdiDo7y4cZyW02NmBUz/mLgTN89Y+CFubBCzFP4fO8PiC3jNae3pHU8EMZiIls6W4BkKobvuNtmOjvbFyOhEV'
    b'1b3obtGdcyq1B2fOeJsq1iZhYaoEavuUluK1rTNYa6tXb1DIdIGxWHYdJAOt4iFnFZ+npQpbctGyhu6HASwHFw/wYkDOQblow2qx'
    b'pR+UyQlWdRNWF7v1gWyPpQ2xd7zO+dYG1cUu6+jeeNEb226LGdcTvQHRtc57BuKOoLdxs3U1MRGtMreRPmw8jerH3D9ITwO5f3es'
    b'MtR9tlZduzvdWOPrn92PBNOe40YZfKoueQ0af/To/TyxDdZextgagMsk9nB7VF94WUfQunmE9eN13oTEnS/7vXl7ehW+u3j7X372'
    b'v+i3yXuy/4OpGFkxM2LzyklWzIKmMyl9pL/AQ3/1Uj5qD45PcoKb5lYMF8Z0tcJY4KYfL7Ghzqe6T7mvb2/eclaClwu8dlTz7Rtb'
    b'mVC3adnOU7pNa69vzUe5ey0rCeJTZ6Anb+Q2I6sKqnbSLVpFtEzhmSmWJGmUsrxxEtoCiGPK+7iWx9u19PkebeX4Z7tpfRwTtKU6'
    b'TpP1Np8NRUN7h+nsy1/g3gF11JJicDPiT8K8Qdl0W42LRZrLe0XTH/IpWHn1nPgR9AcSoN/kWhsxWBXFcyXPFh0RCdoBsxcQ5OMM'
    b'jw8fQggmEi6m/dCcnd6gBT5vZ5PhCFpYe7oFEKnU7DbtzjR5raL94048lEjklBpSka8d3rAYSHqdAq0aXZ6AElozJimVeL0MdaV1'
    b'0BQV+oCpOmtgGZKSDwwU90FoBJkwpFkWhjpgYLCgZbhK9MO1sP+Y79QOaF3TaN6UL1hNwetPlYcxw5BZcF5Ic7ut+CVCamt4juNB'
    b'Q43jBqR6fSQE74x8BnlLRC0lJxY5S7MwYzSW8rmggQHLfHtXVgwzOpuBIwc8/Ekz7u+6qCWnYSVVBxPYRjSaszj8Gy/yME1Cmquw'
    b'hcGccv1OmjRIiAL8WN0z1TbBh3JUKeYYBne7kOe05POiDhGSeHTPHTSqBXBxD5QNo2Vzg69HYvrhhDP9SslglYQ1vsRbVCFKxKpA'
    b'vxImy+VFk0YQOoFkripsQVYwyhcUGE6a4gWUdqlWDCqac+FVq/vAFK/Aca23w90acvE0iWQ0/ZyqNh3ABf0+ZQ99dbQHo3Zu9NNU'
    b'XBnD/Thd6HHaFAJnSlnPJKO81VO1JCA9QcVqTQ0f1m3+sfgV0itv1apiJU0rhUhTr3tSWnMGS7MBJ7wCOidWc7bxmKgQlpT2p2qK'
    b'1+XtMjiGi1C+9W5XXNtj+y1zVaPbq6iB4XkWsbWgnGf3NCu033tzcfM4WrpVOny0WpA6b5Ldmh7FW+/ZScYeU/GM90x/RHkYWd34'
    b'qh1/kfZhSXMGhrsqvWdxV8/K134GNHf7ltRK8xgc2/U75w3akAwexbFK+uq7EJqaqOjyepWxrt6cujSmpTwMumrGq5wu0sg8idyq'
    b'uBIXNIf5QirDdlSlsbHDQBikqiISeWOlDB2F7A7recVYmLF7lq0/JaMq5akWMJO0bq2CuqI1m63C22zJyipts7MmyTKr0xjCfiCs'
    b'B1gvzTIqBax27TSHLTdPw0UBC3C5UAOSNbWzpxnMcDw8kc7caHp4SCsGvsj42ikkFyenzUt5PKJ5zioij3K7+4qL4B1mCY0OjvMD'
    b'xImDQduMFnWrPXMm2V+Nw856iBDZY62CStuzxxZMhEm3+OTdD6eXZwdH4Q8/f3fx6kV4+vrdD6fKNKWpdjkvqnp8cQle8SW8Pgyx'
    b'FYKAx+ODp8MTwsssrcGTtar3siKfkYtLsNpBl2P2iGoLZj5uouJNsmG7ENp1zKyooAGFVcrv3NFe/vD24iq8uAyvLk7ftYZwhuE+'
    b'ESOSI/AhRIj40OPA980Pnr7ce1lUC3JEnpCzq5dKOeRg0Ab3NSbhGKsM7k/UZ4fhRAVWixsMPOk7OPJ4fOo86RytooyNxezDy+zR'
    b'kgFO7y51oBzEvmBshLP+oCFGQ9yzSsnp7vZnhsKaNQyEvnMQYrTKVmOETtI8yYRGiAESSZrHBIJzyeX5i3/Ze/OjqOz0CZ8kdk37'
    b'rt6fO72rpYdZO8IIEljEKY/SEp/TwL0Y0kL8IqMKml5zkK+VTWTDzt68hgej71Mxwv/v/yY1i+YiEz2+Ol4thJ0SHp139qAs1HVD'
    b'OquYFHm6+n138I3TN+QKGRfJGHOGQOCRoVJgihFnaZgaB6ylzp4O952epHhMbpcQkQGpYCpI4uDyk5KiZZUQq+h+bnZ2dnbJ9HP8'
    b'7eySS3wj5Gk8Tk/MqCCCZzqRZ7p+LaIZzv7wMyLxpoBORHQSPsBSF+XT/dCy8EzKlXjbnvz52ddH468Pnz6b7Ozu7JKXy1woGic7'
    b'kPjDEmMIGcOjTRnE1FZjEPfA9RtMCYycj6WCASZTApWDOc3jjHGE0/qjORzcYww3ONwfv8S3Oit4nLWSz8Lcp1TEHISUF4nIPA/P'
    b'rw8nAjNLlgLMnp9+fwEWmGhZ7WV0Nvz34GBvxWjFMZWXeMfknlYpKFuEZbQEv28YhQC4iRgG3Vz9cEZu0xnOrzmxIGmR4Oj469cS'
    b'w9bf2wd4IgRdzVJeF2JdA814c6VNnohXWDNI1fAET+pxkqWlH2KS0RknQZ6i4h1CxbAs4PaT5iv1zJhbBF6d1jdgPs8f5g2KYfxy'
    b'HX5Dnj8VOyMsn2WN+8eEPJdvA5OnJGeQkMkPbo7Pk/ATYnc+gnduOA9zWlXFA5iYgJ9GJFzmaH2AMuFXKxj0HLsYC2gQ1lgyiG1W'
    b'JoMYnjdZFPcQ+7bJjO7swhuvlEDCpAwecsnrdLYslpzwLI3YhLwoyPnbKykhQCyNGKMaDubeGY8NCu3sEhEACCGKMg9UlBV8CYLZ'
    b'PavI+/g9CQDSQ1FhjB7cvoHMhgjCi7ni7Rdj5QWx5/V4fA9mRGSY/AfYEOsRqaEgRSegQ7z0wzev9ePKz/3LN6OzEzwGuQi/If9Q'
    b'YEmScjg4FKsSOiuAxmIxYjiJfOP3Rw5vL8u3dsSihSl6/upf4BXmtMbxmiscrhVvi3quYMMn3AUQXHCE+Ur2VpUIdjV3DLlZBAdQ'
    b'ZW9VjQibzCbmRjKcEEz+VWTiQK2Kh7FwjuLzNKmDg8MhgSAmmEoBWQGlGEx0cCiypUzhX7iLjEQcpTD2Quot63KE0OwBfPohUlAk'
    b'3WILSZeX8EgUUdkrYeJlcCPghNiIVDdQ8qUg65fqYZ4UogVBY97jJa1Uuhv1mnKQ0ZnUuEdEard6SxHfh0B73BnV09bSj8feACV3'
    b'ODfA8OZ5/8uxrVdjvYk2hiOjhkhcoNhr6FYVNHtx+vNl+O7sIvxXMiVPnx3DpcAeOZL34FdvX4dQg0zJ0TOQE/77//uPg8nxGK0a'
    b'YM8FURd4TxJjDI+a3cIb0LRaSS+/BNLzAa0HreHBsDGdNhbfaI8ikXMDkxodm+9njcfj9pTquDmVwkqQCzgqnqBB93YVDKL0bjDE'
    b'p3Ingi81XXQb+sEK4FxHPn00FBCTmmBaEsjRFRzg3kCekAPn+WSoKYLW05xc63U/hubN9kKewO+b9svLwC7Y+q/kqF0Kf7ip5jIJ'
    b'llUA67qfHgjaTrciFiC/w6wlXEVXfoHQvGlbGspDfZl2CSBARro8bldGktMPdlVBeIHP0F0AFa7ADypEEPraKvnMztYz7Wm/S66q'
    b'FWGPNKrllKCNdQQ7S45nEMjkOcS+3BZLuc0K768CY5inzfTfkCfGVfdjLztZPPe4CRcB0zxCrNURtpVxONA8jNK7EZlV+CC4wxgj'
    b'wouqnr6kGWcGD0PytllVmk4s+Pl6EJYitghTCCkTZTBrlnY7lZDV/N5orjIQzToethZDgL/sDlxF7CC92bVERzEo+UL1oL7cXGMN'
    b'CEy/H9w0z6PD3wQGLgwuPIBaDZ7Nv9IEunZ9d7wL8EMFzg0tpG5cGqYJVO0FaU1+/AGnrWEpu9Eyh8tVjLb8UK2uK8avATzy841c'
    b'yPbA00Q38mEBf7cVo0KpVH+0BJusivmDWL34A/nKPFOe2LnZEDd4QF735dBBVLgehPVMBJ7hD+CuMbDHVbpgOOgA+pwa/RtsAX+L'
    b'CpjVkpFsPpEdyZ6AF8rBzY3MOxVCQqZgEBbpANyVOKbIiNljMHT4A9o6LhPwB9yhMlipVxehgxMyCDPFefjjfvCbrz1L6hDeTRTI'
    b'tfdYCKoTFQBcq1y8+JlCBbh4x7T4rUp1ARbIPGLTNmHVue/gZs/TPAXZd1EBb2fG+nL5ap7WbqSo+uPLWwlintY37XEyju858uXt'
    b'Nc7GzUSQHm/Y8SN2LD62mivJa0oCUVnwkWxYDm7sOGrzj37o7jhQcPcMTh8qJHZ8h5VQNCxFOpBZuE+ag2gktAPjtxI1zY++k78C'
    b'F5yKhSp5ywkm2SRTkTHT85IlKCgy+46hzQM+ZI9sp9MraRZrw3EucTbEyJjlBaS+yeisy/tPRTU0WGAjJUK2BqipgPZ3DJRHCJho'
    b'5otmNOo3mC50Dhc7p6GCoAFgCUxWj3Ah4ZvCoGwB/1MCDYLGgaI7h8BRJNbcEwST2c8ttweAIHlmE81abGxY5Civ4rCHnVZrK1pl'
    b'FYUqB4G/0tFop8OdNZVKNOhNmOmsqMQH9/Bo9BYNIRi2m4ssgvBJ+tYA6RGecUDE1yidoOOrdgyI0jupgQWq3CuqG3pGW1KJ10oq'
    b'GLoscz34ATTFXSBQAjcPEIEv5i/Hzs2EErA5VUUZ6tdr29VvRph+dDrIKLxnu2EnN/aRBp0YyXohL0q/4Uw8TuBoEpNouUCtP4Dg'
    b'qYNGzERv5udvL87Clz+evzh9c3Z+dfq67dPcyivpdXfeJEXljsXXnlQm1wPhcAskyVLhGpViRJAKXbxpo6PzmpiAGxzV11uWQBpr'
    b'eLzBrNhotm2xD6Qm/yrEbBc2HSAfZJYu8ODtadjSOnEwftQdErdVxJsJusVA5E+Q0cVtTAk/IXyCfQaIzVTjZShsqjtMEtBNEl1f'
    b'cZ6mJY3ucFiY/8OONGjD/4L8w56ERm5H4UOl2GwHK7US3K7BQue11Q5POmGC4jbBLQbHqedvgMkiuBUpEvWm00C7cgsr8sB85g5+'
    b'NAnasChKEAgt2ePgZuMFBGiWkLOnQU/zh8K+qxyUxRGZba4nGp2ORLKjKVnvJRbMIP+tD4jAbEJLMPYGdb1o17IHoapC33bd+DoZ'
    b'/Br9hs72N1ZaXN2PlPGlwA+EbYiHx5QTdAF/0BHMPuSPUvCtwQn2cVBRrWxE7KG0sXHmy8o9q8nhZU2TLPChSZLjrd5eFP5RtZdm'
    b'fO2H6Oja6Fli5x3usRNgE5/PMBZg8h2xxh2N3b++u4ei13eakF97V+5vE8gfCa/cB3rZmeaSsn1kTWasDuz1PuwZc8XufRnkNVJ9'
    b'dhXA1tfYHUUfjCUHdyO0AM7KxgBYsXvDvAIAW7s52BNkY5/yF6N6pWq4W6DMk2zVAc0Ne7I+tidK5hR0h4mf106YTNG5dtJksE7v'
    b'xPlhNZMn9qA1E9gFxDe6jScSU3Cak4kf7Ak1P32WSdVbrurPN7ntguYSQUptHYccCOBQwUwN5JVnFJybSRnVoXhWIzjSW6GSAbu7'
    b'kcGL3R0oKbKjA2v+e7pxEx35O7O5ydMl/GV0dgCGiAN4FMG+7my/zXeE9mZzH83o7BCaH27S/GvR/NBq/hSaP92k+cGhr/0xtD/e'
    b'pP3hfqu9JibaXw4EJR1jjGddaqKNWtYHKfF09HC4RQ+Crtv28HSLHgTpt+3heIsexOSs72GXfAfXIlqRPCFPV/JRwsp6evBwJS5S'
    b'DlYd2OFDn/KNPIcsxgN5zpTogKM2PzSLs3lgumd1ZnR2BA7W994VaYNQ12vGaozNOs4CB+QcAMIgJzrsfD1PvTBo7cc+YIY9TI5B'
    b'W8Xgb9M9wwa7/abhtt9213Dbb71tuAD8+4bz3njn3uFQ2dg8+sAdbgNOELMP3NNtwAna9oE73gacoHQfOHPNehA3FqeHSuba9cyJ'
    b'sX6j5BNWrmzcsWajxLtaVaNPXKcazOdaoRLgR6xN3XLrValbbr8eddOOlajel+9eg4qCnatPgTjcDIRvxSkQTzcD4VtlCsTxZiB8'
    b'K0uBsNaUiZq5XMxRW+vIpGizgloyu+2xA44k60XxVmIDiaRHIdjTojuIzF254vqPZoHVhoK1na6htSMZWDmydQduEqwvLULbMjL2'
    b'ygsmPrZZoyoyeG0h+HpEFmkeChM+nxo7E1bjddx+Qamx8WNAznR/RBxjf7OfAIGdpyc8FPburhuyBI2iagkReJox9BbqdAzKoLkM'
    b'hpvzSN8QNj0FXGy8h4FRyXMmtAb0SUdDC9pnOiFaT41se1C0AGx7XrQAbH1stCD4Tw+jWv8h4tK66yxxAR5uBdBzsrgAn24F0HPO'
    b'uACPtwLoOXVcgObh48PeOGp81DKPIt/0KE878PmEYKYvyMvnL9Fl/4lwWVDunpttXWvNOhDpZBwIniWsbT9rzwKAtdZyozv8KKON'
    b'ar39qm1abrtcm5Zbr9OmqX+BQnn/ytTk6lqSGsThZiA8i1CDeLoZCM+y0yCONwPhWWgahLnCLNSMpWON2lxTFkXXKEhiieCd4hrh'
    b'KdFqihY6jSO7gXAzobfcudxt60/tRaHhf9SiUK23XxRNy20XRdNy60XRNPUvCijvXxSaXF2LQoM43AyEZ1FoEE83A+FZFBrE8WYg'
    b'PItCgzAXhYWawfvWqM1FYVFUuoqII+ZqWeW0gsgFENbgzfi6GAtFpYkNI09EkQ6hIipMWp9G8KQ444zErGaRiGOCJuQ//ut/IxIc'
    b'ulOkGBcaFJUDcUiWECElYbFHcP5JayDK+Agv0WmV8iKH5+jx/XD0okL5HuJP8Al3DLOYU3hhHN5wl+G1uxAkdU7Px3O2rFJepxE3'
    b'XhiaEHJGozkZWCFjA4x7AyetA/FeEYTPSGg4MvGQDBzKmP1JRUPmRT7W78jVBYRPpRiIpD/esvqBiVAcCQ+TRagYKHCNw00JelGu'
    b'fEL5keFGA08s24Ck6oklaAdAxhAINkZw6aKsinsMsyXBMk9rDqFgGPyWrWAuYRjQuwhto7dQbiGHYNCratgEEkGQL1CI12mWiclc'
    b'UIw2u13WstM0n4nIH3QDtUgcyDwe4CyMcWY+b025eRtVeyKFvNFC+JxJRwBLtKw8V4xGZ30Xi11qlNm8rUFBK+ir1S8U9PSGi3BK'
    b'AnDvxMe7hSKkweGb4PhNfVJ3mD7PH4NSALidJhKny8No/5NMWuuae4Mp7IG6S76DGMOczTDvx1/ExtfslRDVxRHxbwUGQQZvcKr6'
    b'8h0yJJuxVIVnMrj/V+weTAGoRKN00UjhE48cDtfHIUQ9hjmbKTB/tXhG/tRNxPMGRu9SJbdAWelF4fUm9U7QoQlKTmaxrDvYqhV1'
    b'22KqEcnT5heZttScLq4bDAZv6CxP62WMKUoE/D0jF8PDPM0gwBbYEd9U1RuYmg3t1r0BG4Pzr0T1f3IWz9PQj5Ucfh9Gu+QsreeQ'
    b'mWKJybyaw1DMxvkrZwpG5O0FgWRfVUozeYoLQPpUIRHlc3TfIjHjZVp7wDTLClMxWD7tfeTHE0r6jHj2W2evNdxHIEq+WWut3vH/'
    b'ykFed4JO8YaniRqhg4HYBL7oWczdCBjrOgT/cX2QbLy3yKWPnw7Xjs0ew6jVv7kxGIDxPTh3HxGA2zuJabm2RTeUs21Rw7Fya4dv'
    b'0OI2aCxF9MZPfKNmidvMzaHgbeXudKrxrNygcdtTy0Mt51g/EtZ672nfR7etwPgouA0AHy23ad+iqjmS1oH0/7P3bktuHNmi2Du/'
    b'Ig16Rmg2gAbQF1I9aka0qNaIsSmSJqkZT9CMUnVVAqjpQhVUVWA3pJHDD47zASfsR0f4zf/hT9nP5yMca+X9Ujd0c+bsc8yH0TQq'
    b'c2XmypUrV67rAAG595Rmq6vdp0UvgIt2gGoLeszTsvHXrP8xgVAoYMaUDMJspyUt4g8gSF0ESVZYJgWtLut1kkGtV2C0UsT/OKhL'
    b'CWLZg5TLr3FHmnmv2065J/jPe6C97RYd27lH1mxm/cn8cH0lLb1uuo5Tr/4wv98/DkflDDnH+u3jRQg5dkmYJiHkyWBSDOwtf88H'
    b'EPxC4fmdF9XEeNivE7jgCb2DN3S2lBmlNC0BSxaDBImfMyClMVgTQzDmcXAgL5TwaIdXpJzhnKfPUnlfoNC5dJ+H+SzyNMmDMqUU'
    b'ErdyL1YOFHJPyALBmBuDB4PC4z2pVgCUJU2BuecZy5LDY7H4Skqx4PeUEsz79nXw4jj48NO715fv3vz0+jsRvgOxyWUVZhU5ZO0C'
    b'bPj23Zu3b95fvpqsY/L//j/HkwfdTFalEhk7pHwXMpTge15iFR1BWGKO6b6uvoP5seYw1RyeTyNO+3tSfJ2bK9PP6sFKNTI2y8TO'
    b'rZDSyoq6Wb03hoA1GTCszO4cswYIKC2NX/VXQkcDLB8F8iOpujR+o4s1htZT1suscYxVwCdxsljo6geXK7x7c2UdYHLoYRXDTViE'
    b'aUpT0Grlm6M8WhwtosVRlmivV22O7bKKmuaBd5E1RO4BXr9/vPBQLars3Zb4ctgn2WaYT1Del3AzHo9vwx28VSDbaQkZouB8HonT'
    b'dlTk/A3ymHxHF5CZEQKU4QiQdVKCthMzZckq6SzYeCpYIxuSvWk4GxRaPvDPUJo4iUpynebRDQmvc3hchSUpb5LNhsZkKMZjR+MI'
    b'CJpvHHpmO0hteM7W7rCIxREQnS1sB+rddQHXEDCEs0lnjtYuatSyV69o0MBTve39y/uniRPk/eWfr2R+wDUFxTQcayCbMVRLOFdu'
    b'yFXOE1xAxm3I1MdILaO3pIILnuWLOpCq/9qYDxY/YngTeZQMdSwZbRYYWuYFK98ENaoHJjk2QbBeNzVwOG9uAmSL1zWQlpsmIJ3D'
    b'bLh3WQMofgH2wDUwhCaI+g3YA6wKGWkCrgWW+NYsmIogs6RERoLh8yAfWHE8doAOhPlxSrJ78t/revKTC62YoxpjLgLakRhZlHJA'
    b'laipzVkY5GOPr31rmQO01OegQ+02D0589hTYzy2j6xWXpBV8yCHaw099o2uH0Z6B+tQyC+UvGIVppOahwW5AhaZFfLdNUT18MmVR'
    b'WRhIxt7O5BC9bdg4ZIhM832+qG7DAlI3FpRnttb1VJ9F32b+J3wAWOm1ERHE79R1b9LD8mPAB7RRqZNqiwS6haITi+BkynCoAT20'
    b'aV7gcjo5BVyeGrh8/+0LkHvuduci7V+yUJEuIxalGycpZoUdX4dgKjUuF0OKLq8jzwPACQKEZh6NcxP9lNdIMf64NQBXE+wv/FBP'
    b'TD/U2cGk3K6Hmr6SIxbHyVWMKebg4WN7T8p0cqodFZqCycHkmvYum59bDo13PiYAfS4n0wPyhEwnT63icWp+ekxx/RgylpifuD9+'
    b'R2RxpiZK0TkNZHYTR57RmEErRRzQuw3NStqFZLTWPSmnwJhp/1NLA/pA9FPEVsnRIR+/hnie2cTjMmufP7PLSlv4hTMt/7UwrmPU'
    b'TbP2kJQzHs89wAXad29evjDZyDl5/ebt5QdyRF5mn1n+3BesPp1GOkBwSniyz5WUgepvKP2TIWEMuK9GUKur8JOlr1tP+gQQ2N8b'
    b'Lt0RfoNWxN0ffcShxBqwjWP91uf7AEUscR8uyFDD/liBaRw+yzdY9kzbBGRQX5tvxyQKGD1w+Qh7HTmT0O4yJhhoE/bA8WlXtBYd'
    b'EsScHMhX2EtQM4LbENYdgDTuBmV2oTLUVELpmB6cz+nTk76g+gi9ExkCXIy48B+CFZqjmovSvnUiZcslk++1nLfYDo80qY0kKOcU'
    b'ONixdSlCYkwP9zARCWOx9GLmoZmeNB6AHtPlI3imKtRQXBAzCo08lMQB6jcOX5YewXyFHnFjDFUGR5xjIATIS1LQMMZGmI3HyWzh'
    b'xDx4Q4iisCgUEDk7C5r63Xl3a98sQ5r6YE9F6yJMeuon5R2s/egkbdC+aQ9i/Vf7peB8Ex6e/g/zug/HdR9O6z6gL6oXT/7puaGr'
    b'9R/NaboRs/Ufzen6wnCtfaqZrOYr6/vZmqDmiuv72ZqU4c2rU6EdOGiuRKNy7YMv9E4nMTfyTPtqKb+1L0o176d4P9o8sSwNX00k'
    b'esJoGr6aKPWG51irkSaT2vUrU4HWRAZvmD/516/HHfh+NleshzX4fjbXaEZGaB+kA4H5k3+GuhO472dzhrqPue9nc4amm7r+oSWp'
    b'omr6uNEXXXPiY1Zb6YE+5DV8JrPD2URz4a/1HbDOY+1H19Cpk51tbTUPc/2IDY441sQaG/hdaMwJto7gupRYIzQ2aHJN0dlQnVeI'
    b'vvXNngqHlp1y2GSd1yigzqRjXM51dhybhzR872CXsqDVY8JnqDE3hSvmLB7o/uq8z/U5KAWgfsWbmhy9vf4gN9ai3kPaz660qnNe'
    b'W0pk36zkkZCszBIKDzXhztTwRy3+tzzJp5bBUM+Hx4YowltuZTaHVUlMwzRtyKfJc5o25jLVc5jW5S6VGFCL9S5mv4ylerZSBwf3'
    b'Wr8OrSmHqZn4cFizEZ6XnaaQZCVSFM7+2Aq1FeJzBdG3OlWZ+4tUc0vARp9BEUGou0oOCZZQJawiKpHb+q8u6cZqtjXWiFV0OgQX'
    b'hOPT+Wx8fHZ2wmqA2ZVjif8fdj05fvpsfHL8bMa6theX1bs+OxmfnByfHWBJr8s0JViilYAdZwOFshRKz8GJYkeq8IaSkMhs3cBt'
    b'oJThUnp7QSmv4burP7/88Sp49+bD5YeXb15Ll7Aj8uPli3dvAv5d//ndv119CC6/u3xrdnn0mByRb69ev/gBmgTvrl5dfnj5F9mV'
    b'1aTiZIcBVzgr9BFBxB8hIh49FkTCChoTVgeexhPyOicv34xIlpPrbQJlwEtW4OwVlEopONklFQWqwjqciwLLI/OU/FhaPUPsFgEU'
    b'aoxZGfHRo8cMIN8Jvv/4jZzMnr4a8c9YMJnRSJjSouJNZs+gCQTAPSbXNItWUNcXKB4qVoiqZwcQLIL50cAdAac6vibXNAqhwhRu'
    b'WBSWURgDFCg4TWgGBdCg9nKEz1Ss655kUYGO5yEUksElbe7E6WKNAqjKRQ4fPSa3RSJKxsp7i5f7JsNT6JRkY2wtJ4kFu1jMIVxA'
    b'O1rhomgGFeLY3HnbyWbH6641np5hvDBz2dfkocd05ws9rbYqqnXuXiU1VNt2SXK2bswUyQxZuhYoo7gjdgmhyioa/EGHxPkn9o6h'
    b'CEqs5YQU+aahT0P8tdXQn4nebtSUFzRLftmydlgwy+2MWejx2mNtNQ2i8IH1ZVmv4w81mdU5IlKaDfUpHUCUyQw5gDGYpVEUn/CG'
    b'gxIUmZVWuCZXvKnCU5M3xrIUsgtrOG+dLh+ptIhmHeiMb4yVR9qgOwlFkZ69o7IN1A5wFYTwLzL+UnnMBVQzSdFhA28329VzeQeg'
    b'e4fY22CSkfyq5mYctY9ytZKiWSbgC7Uqt+KC+GQWWjDKK4gmjVUV+JTljHwllvoxqXpG1UJEJvFYDIsuICoNX2VhCrWLeCAihkWf'
    b's8psUDwEBEV/7CG4NqA7iVgpeHcgBusqqaimnnJrTiDUsMivt2UV/GodcBjXPeCmaHvE1mEEcE5V/KbyjwE8ZHT5XzUexv8MREDJ'
    b'rxhdejh4LhYFeRHEdBFu02oo5z1CTewNrQLeTVAfLwHNfDyaxoQhIat9EiUbVji758BcrDZg4MDHp60Dq0DlnoOy0uvlKtkoJVPX'
    b'1YJ4taJITL3GFP0gsCvJcbT2wYqkvAmgtmD3wVCw5d20feQA2WT6zt2hCg4NVJv9dl32gCxoJcq9DtQ0+WWbxCwqohtU2aN9piAC'
    b'RBFN95gx70lxAzN3jO2GxZgFPI9/N/hGryashNd5EZT5oqIYi9wZN2Y/FzA8G/puo9bHBch1+P230e4YFJRmVbFzh8DXFzOOdIbO'
    b'+mCIQbAO59PpQNnZOauVLLsjFjY7C548uOx/f/nll6DoQWu8fQCAZ2AnVibwcldWdJ1EhkJqOpnPyRNdABh8Tu6CX4OzYyhNhVfG'
    b'xWyixdFAdcfZM6vPahfkYRlgThqt22m3bizlE5tvXdcT8oQMh9PJ6SkZiysKLrVObF5CmSIUxfXHZDo5w8sRzfG94OgLYZQRx2he'
    b'kms4NntNn4k1TGENigDB7xDEiq7DIyDrVLb1bb/3mcp1m0GFZ5tGzjrQiLVjcxtH8R0cx6p5m2EgTQpz6bmVPuYOffTY17mHPk6f'
    b'MTjzZ/3gdCT0s677cxsWQZ6kGNZt7499sLZl3oprd4OW5Wza6TDawzXcyTUgkISdi7HzAQAyMa69zjtzYk29RtwR03527411T/+z'
    b'PThYp/cLC7MLirwSd7FOJCcwd3EJGFM7BqTo5OWeSZ05uAjVLvNePAzQcQIM3RDe+XF7CKRweYBLAb6bbzgU7x3jrJ90P+tsIeYT'
    b'BmCdzDmsHvwHUD0c6rIJzmra94bwkLlPDK+jcpsz1ErHTQBsWawXZeij194BbYeT4RH44FlDN0mJx0CJ4pHVS7YYCzDuIXTb9Dws'
    b'2I/RxXQCggPbSnteMF/gsvc/M9yWgjqmxRaMpzRTMubBSNNJCn1Ffv13GnFjod6dJcUZSsnz+YXBSDBvj/5R50HOR5D9YHTxWxAV'
    b'SZlAkTY2ZO3whmDzXLJAllLI+OaZgd0AJAyYhf57+xSMu9uagvXNQZD5Xc1A/z0oV3l00zoPZYfWn2wCt7pF2fgOANbhXbLeruWO'
    b'jPQf9TmPTBwe1IO9sNizVnhcfx5q7hNsRezvWlxbPB9XBzL+H4nzyXNeAbNmMw2rjjVH6e80a5T88aNNq5xvomewfhFrPXRUBiDg'
    b'lHov5xrWerr0oHV0bneto4sErWMNR9O6m9jSupof7G41umqlKeWb3awpFZxHmgGFDYQXmXaKUks4rAsaXqVBRFoFwOuqxph1SPxz'
    b'V6ZJtCgMuY3ioi8cpcdNlhmg8kCDjNNVzPijmv6nEcmzC2W7WOW3F4OULkSNaM2HAzTdti8CT0RoFKLfhBUkhynPSZqU1ceyKj75'
    b'NN/VHaiqWH+hBhkMpB8JZMqclFUxwStHHRF6B5aJfwwmf88TuF8mtARn8eFGNGS2uQ1YR8RMjKVUdxXCjfKsCpOsBLQAYeB/mB3G'
    b'8mUxbdD1vhT3MkSDxc9nynIokdtf2E4wnyYMisW/B7rNYDCwEvYJ6gfcsoErGq0CTGFy4dtb+GFEPg6gWZan+RK42iDK1+ttBo2A'
    b'zfKE4TSjxXLXARZrKLqJnIVlh56yreismEx7522lFe8G9xTQi4FQtUnZbysaptUKWCVVf4q/ChqmECuCZm5h8KBVyJOI6A8ETGyC'
    b'1gX0AAqk7QXSeH/O02B+Oo81s/phcw+mHOrcfJ2vQWrlQhs5IsciFciWa4/dGY8bIVKM5dFmMG6eQdmz/SJa7Kwefdd4ItYo6eGX'
    b'bYg+pT23xwwb6DwhX2KecW9CGHcnBH3R6xycdbbrvmsFLB7vi/UuhJuUFVdPm9SIf3xO7hqV04gjTVsoFfAgiZStXV2dlATQRTUe'
    b'16rEkfWuV50g8HYeCHnS3tvQxcmeUQ7PrtbO0YYWnt6drHpxB2se959rB1NrxWMH9iMfCXkp7Ld2r6JcpzHZJ0A0ZjfJ1FB4tfta'
    b'LO8Jox0TAl6AmlXWhqEuyCeCckwAJV0nZRDtopQ2dubEYHbmlyZI2HZf/T59AgRj9lT3JqMIp791sULGLGhn4U9J6Ul5Azvt4NC8'
    b'Yp/U8tgnkrisiQr2xInAmafJvp5w0nrkkz6VCMYs+NUupft6Aw4Gg3e0pGERrcZYrwChCcIu8m1FC5QkQc93A7kQP5eYjplH26zz'
    b'mJYy83UP30J4ZGQsB+J8Frz/8LdXV7UiH8Mkviwc3x3XHSeDJ7X0P+HnUHmgTOs9UDisxsOMzwP+tyMhiymAkmg6c18FLQObbinC'
    b'nbbJ97yTXw4q9bBKQ71fDmgdW2Y35IhlnKu7R4x0eeBYATC1LPFUZHLWrdd6xwZXA7dvkKw3W8gOUgeDfzd4sg0jLsIkq4WAXz39'
    b'Hd253r2Tod25q0z81d5MrmuI3rHFAaTeW8MPpMEnw+fdoAOp82E4sPyoPGTT5C3l94nyAGnyfHL9mzwAmryYHF8lT3+vR5LuX8HS'
    b'MZp9O3hRMOx6fSMObOFP4w11lgJQoLNuIJkwpZo1KVtEJUcq2XtU0BgC+Hz9PPY/TRkvBV1Jqqq7bpk7FYYLvo46SyzurGm6A0uL'
    b'JGbj0xygOnSu607l4a3CJOVmf8/sYAjZ1h3C4UVmE80UpGsCxfcZgBjO0LJh8STdD0ZRWoKlAdxpHgMg0cydpaRvd3aKKNxvxuZp'
    b'84HQSS51+fcUTfKGJNVlTDQmGvRmfj5TyNKOkcf4ZqHSaGBbobRlCRkJlrzwr+ukeT9xdYw9uCtzKc5sc2IJ54ZlT1uw5yPjp9ob'
    b'nGPLIBzzM8xU30cND0o+bMFE24qetVC/vqHcJcBFCW9gGsldHPApmvwGsqyckUPtNoVfTnx+UWwUaQA1aUabKN8h00TJKNePTfXA'
    b'aEJl/WFxD6GBPz/70zHn7pIHy4305UVOk8E03sNQajAVZpV7hqZG9XO7qdE8ws8vbFpGQ5jTSN8if4vp5OQZt4hqs8RY1Ge4VtFB'
    b'RMG3TdQ+Y89N7oNjOW08M/W0gSu1aa5alzCKtuutsDS2zdmgZN+ErQY+3JtN2icr2mMCbsw2YFsk0epT5tsionrYmfZKHdoBQaCv'
    b'5WUPxN8gHmwqGg+s8HIGoS643BjaCUuDF29DJBr8QxzKl7YGzrHgOWNx88gmnrwOP3hrGq3zDCVwreskrib4s3yFykcw5I8SDAsC'
    b'092O/END11tKb+Jw53blHxq6QmYw6GT3FbF46yQbHlhYsqLZMJEkwweChOqF4A8D+15WYVG1VYIC8Jt4kpRZOBTz4WCHOv7HcrYH'
    b'sLg43EnbH5d/j89OJ/NTFVKC56Sk1RaK+RX5bQCl4dQlYAajNWsjJbhFQctVMJ8KqX3UA8gGnOUlpFWexsYbrg+o1VkQ77IQ7Pzs'
    b'RdUAadgMKoOA49P5bbBKlqtgE1WDEYFMvgfAKcZwGVkqGwVdy6AuzITslnKymWpc6WE2BMPiApWmZm9MQt6CkMUsByaT9r/Qe+3S'
    b'DN+rJew0m/C+kJIs3pag7FD+EuhxtgcoLPwitc73xp+ZiKUVYHeSUZfPA5FMmmdLdup00Hsum2e4DOhikUQJzaLd3qC4TiWM/77F'
    b'5Jni9t0X3joPQTzI73YPcigKKtKZ6vBOe++p0u27Gvh2ZxzLDUGXaiEnMgIzZCNWm4gZgvTfzS6WtKR1sr6Y3VwBye6ui1xmX13m'
    b'sns5rxnZy31PaG5PNU9C2dl4zWj93FeO7FKr8vyknlPwzNPeQvh0OfFpgKx9Mh7IGlj34awhLaVZHBYBylHc+pPx17fbigtNYifg'
    b'/9e05DIS81hj/7+mpSPYYB/n16Z5QzuRX7lMsuF8Am/NbDPZJKDCQBFRswzMUKknlYJ1QCNeESbbTKK8vDdQjq/muQqp1AZ80g63'
    b'cbp7wOW71jxfIQrrdheA+7QdbuN8u8OFu0tJkQmjHuvN+8QSW80awGfKUHTmBa+xLDmA/VR94ohiPQfRWJ4cxHhfPnFu7vYRvnS6'
    b'p+ScKwiPuNQ8VnaIo3WYbcMUS7in4e6I+c3+qzM/ncxPTscnT78+I8MzqJ6HMhWkYTNzM+FVGsbhhkuFZm6m2enTV1A4SJgThX3o'
    b'kHu7IbCe/0wjETBv0HDrszIfJmjq0ac1nD2bslnF+TrJwqw6ouBUCiYj1mWfaalaYcOMJaSH1E1JBrqh7Sb4lSW1wpREbL8DFJNg'
    b'04sk1vNo4RxPZ2yKf7v88RVhHYhoi1D4LMPNJt0JiFUS3dACYabhzgA5fMZ3ArItKkjQPeGgBPowcxaLawXZC4sro2Y+W1YrAHX8'
    b'jIE6HlcJLci790Z34fbNhErI5Wktbf41684ajrnXwjXNKEiyUGcU3DVkIi9M36XSdOm50TbptmQYYhjh+ZmSkrx8c2ClX6on1S+U'
    b'g6k2WUyXLExGohtf5qT6JDt7TkCUXTNGr3Pw1jMg1Q7jyYHkcfR+9AUyPmFtGeZT3FyEjjfChDE/ZTdZfptxnxjjm/aX9PYWzQ2n'
    b'b7YaRI30N8GMQnLQ4QAzlllWXvN5ZLeZnfrasCTHFV1vUpCi4aTeodqdG5b1tuvwdNoCDn9vmZZPU+MZTfOe9H4vymR24v90fR1s'
    b'rmvWwHw+PTNnzp3uByEVMEy5T9FP++QU5bvKfbzyWwyiULlMNQqtRgTK5uqJOx2NNGRYuvg+TEuqaaCX4Lqw1BkNn+Jy6UuoBMEA'
    b'SbZVFhzhaIFbQC6Yu5CVPme5/OihxJakmRPUfWjhTWqk2Wn3kYAA+47E9hDVYZAw1CkSsVyyUIKaU9FSZMuC3lQfQ2sqF2x3b1qI'
    b'W1/FB9FowCnN0jw1F7gU//bci1EPgA5zuTc8mxN1BuipxQn/lktdK6T/8xGd0Uj9hcwPGZ+5VR5yd/mkZwVcuw3htnwOjA84FGN6'
    b'HPlJxCULz7Q0vuydD5q0zeXDv3/4YDEe7gfzVD7uW8Ewfl83m6+19O7GbhmYkk20SnVc+oSgF2DQJnqAVwiOLEOPwpKltOPc2Ogw'
    b'CZdLF8N8DHYvXWgX1ADm5SNRrceZ6HHWpQfnsxd+6aGtN78HL+puRG9/Ha0WvCjfYl0bqEoLma3B9q8jHEoaaoVqfS57e1KxPoqQ'
    b'yfgG1BKRhxT/2AkuR3otYL2QH+LJoUcRG6eDZzc4My8aZfMM4miMTtDBKfW9IQZ5Mlq75LTHIAInXUbhxLbHKLxnyyjiRWofbyPx'
    b'ICp+DAzxfd/shnriQRxqhNb3A6HyN7bNk6zQGBV0z09PjZ+eeKYi5mJk4JgefMFJHbdPykT7F5iLIWyxgy+2j1cDM/Pmw79bmixX'
    b'yL3lTh/5+xrdVqtEMhfQxIJClw45MG/tMbDqs17g8CTH0Hid2d7nQVwvuMmNhyGYC8FqlYCKFtjnjI5nc/Ty1b5xVBspMRCLWLtL'
    b'58HPyYxxkpn2enclzJoZw6g2RMxDzJkT92SAf6bvtnPkuDub8fBwCBHd5YwXg9sE7DmaPOxvYEli/ka+W8doORZ+bqZ85bZB31IP'
    b'Bj3U7aBJ0iHSgPlZ22YFAV6Uk3CzoVlsovg3h7Ls1+S5+fh021t++LoQcW7uXffOIO/rnWenDZ3txxl60J/rG17f19r0wblNBvVd'
    b'vTED514KqQfijRs49xJGPRAreODcor12tBuxEwrvnKCM7r/bcrFojFk8dPXmEIhOas5Us3+CatOYkzaynnnapvPGDNTlOs/RJGnX'
    b'A2wgfrPEWh2Vu6285Ow2synXbeEPanGa+UNXnGZ2hArTdVnVdhSatFzOEv9s4xyxSk+/rLdtcXeUpUCP7VKgZjPnOWdNqvEwmBPm'
    b'F1LtnJvIoUU15UkL2HeUDgowc5SzLqN4yfHhh7HJ+eFH8B6HrsPIa711GOuc9Bpg2mUA73ntMkx7hmvOQ3lyHDU2ZsRx1cx6ZhzT'
    b'LNZgK/1CdrHv/vb68seXL4JXV5ffXb37ZxvFeoxebxF7TN5RjkCoTVNSIkoyo129jIqwilakhIJOGxqCMTgK07QkeUbgbJYVKVOo'
    b'W8OhxTlOPSqgLS+MU24Xi+SOliRNbqiQVXRX2+DuKNhN2A5AOQd+5UEdNf8iD6y2/7ggvy0Gv0W/B3eDNgT9Xtt317VvsxVRgf7v'
    b'2mpoGgtRQQixkOYvx84vZ8YvHh1h3UdHsLFtgDXfnH6O8VB91M2B6lePLVGHN59OgzLNNywWVH2R/kmfYWNo8Kv+8XMO3grcMTKr'
    b'RI4rruc02rEENvosWSJr9YNIVFYHxKtLVZ/DqAKXjIKW27QS+ez0cpt5cRsWllu2joG2DB9O47psHk7DmswdTrum9BdO4+Z0HPcw'
    b'uEol6VKrFG4H9oiDpvInmN43ModCW7oEcwbSToBjjyCscbsJbuiu5GYCjPYxpVj0yNHqMdbUL/HkiDAEAVuEpvy5o4f6yK8+OUWk'
    b'wK+zhDiLq7OAuNYP4TD+ednVlmH16GAv2d/ywXvi+b0Y1pzj5mni2b0Y1hzixr57GVuEghpP0iKBaXc4gh1gAQORwBq5SQdgyGAk'
    b'tFp20wES40ASVB1DaoSE90YFat0Lv2dKG1nBNXIx9N0ojV21m+Vi2HLlNALidAGXHGLCvPIau5bhgiKNifILTmM9kYBPsnCOsFEX'
    b'2D6tno/SEuR8wQPnA4eHyfNBmnucL/JA1H4Dmq79iCRa+5Unc3Q/K8qqWTeQi+eTRgCer9p2e76yHXXvScMyySTuXy1dh92swd3I'
    b'c3/9k24vpbBDx9KL6Yh4asdxHZ7PGmtEGXqVPd5uisABb6YyYt7W6djTqXYk8QjvPgy7mXpMi91GTodpXQdxA9k9WDYMry1dHDi3'
    b'z3FzH7xc+nZid0jfXvy6cLo9reumDrTb6bRpP/Fe6N5FvwGcXrWEozEGo5fKnu/rxRiG7NDn5NwmWZkXya902KE9WqlmXCPFYidU'
    b'XIaWoNkA1SCiKyu/OQ5L5twk21tqLJgAF/LF2ACpQ5Sm9TSQ2UFHra2OW1u5gkhLB1f8aJuHKSi0tPZKvy19vFJvSx+fsGt1GWMV'
    b'qCdOV5VO1mmPCY7s9jyZbIfwT/xfelfBwxQCCWkWpiw3Xdfkr5Pwuhy6Ctr448AkvYYzZl6cHoptVgg3nr+PAz4wBrBAFKceXNly'
    b'DFoz5rrU1ZxsuQOpNQLoQneNADoQYWP/1sMLLj6YraoBSOuB5segGf2Nh7wbhLb3Y81xc87LPrHzzZSpDkdDu26Ez6/B7lTfnDC8'
    b'lhd1SW/dg9JcZcb+vUEX26e3o+Tdu3P/kW018R6E3fji3gOeTxHrgMGT0eG8NWtB90pD0UDrvnNkNmo5RN4ULvbjCkul2WXm64TF'
    b'zqbg45kPatOt2gM4K/BpA6/nNN0N2McNgG3Ut9t5W/fB2GF/q6YttnJQ10efDqPF8pxcZcskoy/ybJEsa4y9UZjFCWZF2oTVStRJ'
    b'eRtWq08qEAqcCqsCYE700aAH1kVJNnpUjQVSeL8BzGErGJF6lZUhxz7QHv4O4qQQmSu9I2CnIzi6HoxMovLzoFN3+G+aZHTQBguB'
    b'3VAqbbWaPo6F7pp2vbDill4G1LAuJZAgowgDerfJITmGYeIDv4GG7yL3h+8bf1uvaLz0NyirYhtV2yJMOcf0QlksgEtC5vUiN7SH'
    b'9G6TFOADbqjIIiC5GLOQaL8W9HNCb2kchJXjxQQ7ASpNmx5l76qwwuS4Lz40m9C7pKxKO7TLG0yHx0gEnIGKJ4jKz0OkQRs8hH4x'
    b'7/68kDsqjFzw0Wvmqh0V8rZf8H5GJCD/+FEMgalL9L8n63AzzPJiHabJr5SHhTv9eS+3Z1LC1iax6PjJNwGPUrkT6XYi4a6k3IWk'
    b'O5N2LxJvJl1Lieszeubbqp4e4B/si88LxvluXkfs5xaPPLV5zlE1j6h5CB9sSVq6voYlSR+OTmvidx20lTz2EzqcBPF2k0JRJXAm'
    b'5ZSuBWTeQQ5IcoX/SfKsIbhWZfxXvrPCmUWOKTysmjIzOK5VI9L1Ana9rRjsUpXTEndJ53JaTt0ydDfj4GU2iYsW+cFo7vPA/Y95'
    b'oUmRBqhcIMP2bluDTABbIxtYLFM2YP9nUtBMp57fonPCrDscgOZVxXsIFzM8cf/DhbxgfleD6PpY1ov5A0qCsCvkMaLmCleegxNO'
    b'XE1WNtsRW50hg4m0AzLbyzXrh1LwoA7AZFsPII19dVmfbOwBpTh9ewkj2VTCYYEerXU34B+8FrGEgDq/YCarOcHXea7lpeZ9/3hh'
    b'7QlLb3oAUbhqw5/brbxwJHq9ML7RW2iLYLgMwiUQC3IPrdNY3xeZTbWhr/ULz01st4PMwjxm0PeAW4XpIkiTBdViV+3HhWyDEM1A'
    b'1phGmOU220zo3WY4zqBu4xISckGtamc2IpJMgtQLwwo2qUcxMpyb4Y6YzUrSHZQwisJdNzLCVIcurwYzYvKZPS99I7b21yQezMUn'
    b'/2ztiZPnpZkinueuqb1AjkzOp2NM9paMUr96zFsc5X0W9OZG6FnPebxDo6aEEeKf46nqtBC5iVW8ZRZmNefYE75piewCAQisjQeZ'
    b't4nMqNIM0frhST3S2bahsCaQyw+l/JMn0RhZUO3rCl2CLZmL+wc7+DQX5X6uf5N0fpd0fpv0eZ90faP0eqf0fqs0P83NVr5nerd3'
    b'T8PzXf9n+p1YiTssf2/brcmMcO3A53RX/o5srUsXxc+6tDa4mfRqDRNxaiHnKxPlJwkkkPwNlF/VgRDGkbrxnQV31iKPtmUg6ZR3'
    b'/N0XLM9odP9BdBpvGkfQNwi2wExqQQ8VbNFHvGHgAMuP7ATwTwcsjIAfjtYxFBTjOIn5GxOuQY2xHt+CH5PLbZWPY1rRqOIzE7WN'
    b'yyqPbkqoZF/y9H1YqW9EonBbwk00/YPoAbPFVHiGD0ciZm5FEtQ81fhuDq5eX737898G9gYZwQ36lWVfUZ78+DreFaqyzWQd3iXr'
    b'7XpoYE3fIDtvu7M2vmLFw/an0lsIuQFldB2NYhEYfugAG+5l0Bz14ba3lDPxR8+98an1reC5a+zaYIpHSIuB9+JpH8x/X9njGRxD'
    b'GSns+6t9OPfKs4eyzqAczH8Jto9Yc3naw5rkrGWZrbtN20duuInt0V2C95prOiXk7FEz9AUPWVOpSt+9h6CIPLoZfy7HLGpxpH5g'
    b'p1WcWtWkoXLoY/IBUoLOzsl7gAJ1R39UhbGKMljPWhFZlAHWJYLB7BrAZbA+7gfg2AFw1g+AzKmjljDvuYa5AQIi0kqRj1TuBZcK'
    b'sDYcw5OsdcdWzXK58D/PtEpROKNHOvrnGvrf4+aJuZed0M/ZtIP78rhHbwfx5VmP3g7Wy25YF1P3oVx6afpRXpooL02UlybKSwvl'
    b'x+cc04rkQSOwLb2xm/ze61CG22MI14tQPyYvxGrOya9j5gEpLT/cdY7QMFppej7Qgo0gcDUj15BrvDae1n8XAsHdVMGvTOHcw9fc'
    b'T/bc5dyQ/z3+56Vfp3PgREZ5m7Hd33POLt188TmbLxwN48rnpAadreu3ILiL81fNcC4e5xxh0Uw5VePs4NCyLmWZyjDq90Svc0OG'
    b'wl+N5AtZXfvgnByPWVWrmKZV6DJRHYYIvfWz2LG+/VFyM5sOkPLF/3UkY2kvqqPecpUsquGx129Hobdmhh6OdM8Zemi1doY14oaT'
    b'wLuHiPEeGRB//FzvSJgmywy2kVS50Cnz/PaevN9syKbK5PHHgTk9rbvmNiOe491Cuo28AhwuvjRanl7cBUWUe0cHS272UtmaBrdh'
    b'gZFtWOukXOXRzeDc96sbA1zuyoqCww9bMnSzfvL0UTVOsb1brlm1jcKi2AXbDOq1QGP9b6M1ey6jdo0Ne0N3I23F6N+g1j9JKro2'
    b'vCvAOUK1bg77dXwhRJoXpSm3HbAU7K6+XMkCbmcT7jdIN7ODSZimtmuIm2NZ0h3TnL549/L9y/fB+6sXH968C769en31/csXLy/f'
    b'vbx6zxTKGuJ+00x2gFROcvBklk9klrAO0GSM5KIW/q1DLBBsku6FDtdoniywhy+7MZ6xSZpHH6EFWLJaT9uhT6fu2TcJ9ZMKaWGr'
    b'dHr3OutdmjF7SU0SlS9U8+MzxpuHFV3uyHW6pZsiySpySDZJmoYFOYRUSLT4nGTJv7rUh1G+Qcw5kHMOxHXD/qFK62R++vX4dPbs'
    b'ZES+np+9YsUtZKmFbVolcbJmbuRhGrAls80oBYjT2bOn49Pjp5D+8JkDQuBGebBzrb8+i9Ovnz0bn82OZyMyOzkBEI8ed1lIUoL0'
    b'S15dvvvz1fsPsroJnDb4PcpjCk59k0ePydsVePnNSJhuVqFezYYcEnzmk0Oy3WDAwYEoRkLS5DMtCVhDJuRlRVZh+egx4VVBVjSF'
    b'4ykC2michDBqWEF56l1JaBaFmxKqs9J4ggt6n1L6mR5t8qJa5GmSq2osrB+MFpNrWt1SlOgFqYVZrGjs0WMyFJjhB1MCZH7UmANA'
    b'NFGP12sagjUnYFo2vgmwWQVdhwniDP87HgPudiQsKD8EJ2RY4tSlwgFqOJMqLJYUsr3CNXAcW2U66nftnj4zLe44XMhAmB2SGJkG'
    b'JjR1YMiEmrV922I7Xha7pRXQFbuyWxqiSlIEvbS0hfjMLInCtK1hWz1Fs3WY8RxdebHjZZCZJaVY22nsatv7ARfRioK8xfy1gQS7'
    b'NXdrK9a23EXgFgZKtQhIYdfWQXn3+7O2WM2l8OtvKKoPBapH13a1xjdfY1bb0Gq32GIh5NskyxiioOSXb/SmopUWNWIEBNO8eht4'
    b'zra3nVLly7peLBLJaqi4c0ZvOYdmVUlNS3yfEqtmRyiHuEjzW/0YMAykGApSd3p9hU3NVvzOQNabZPy4N7bEuLI4v5VxWVrDT73S'
    b'p/2Ls1310zY9cJIvfFrTQgQuSMMXRi9oa/jUaZp4x3oGrysgIkbng7lzNmYgjJSmsNCayogXMG9+ZSlX1j18U0rPG6yl7DkfTyWn'
    b'EKg4mMiKXsMBW6EIlRCRWZt2hzvVNFgkrCyxsLkUdJOGER1OTR8Y+jmo8oBeJ1UctluVtMZdB1hEi2CX0DRun3y02AVVBRprHQDf'
    b'9Q2FjVfPO04F7pJrZyLTTfgBeRbXBgrW5p+UWArfwg2W4GG8CHzltC09Mhcod8Vob+zSkbkShWbWRSF8bM2TzYUJnkG53YDke98A'
    b'aQ5tuynBt8MTK9wcMgoix3oNhT6R89vpe7qHBy63SYwsBAsu33dV9w7BpmGRBctwE8zi/dYjRekHWQ/dlIEJsd9qNmVAyypY7GZ7'
    b'9pv36lfQz3uNp/r1Ho+hxtnoPTYsyj+3W+i0xrQAV1mepJp57bakvcUrs+alZUetnqE1wth6+VUa8kyW4H43DxdDALj6Tienp6za'
    b'NFo4tEUpg0nNW8+c52PyU0lJEIVL0FuVFRke7wiryV2A9/4C08Zeh9ENKNDnO2a1m+2YC8x1wcpeCmRqy8ekQI17X4YpLdXI2l2N'
    b'6WrOevQ/1d3kZYKhxt45pJ+LctDa1s3gtCcMdxata8gwK1XzNE76AtljHnm0qJ/Acefe7sitOAROtf8OwP1a1xszZbVxH5ptqXjX'
    b'c9HDBAKB3K0XTpItyyYoXYmZg9jlDh5PuuxBfffW8f33rofjCu5SryPy5kYbqzxuKJG1hM6r5kwga2iObFa05sJYS/NmyWhDl35S'
    b'wHV0SuWwKQ0IHgyi5owrA1l0b/O95fEcN+RiHZ5KQ8WnZg3mYoeFtcMVIzu3JOcx23uMXNgkzKJVDlZM9cyTKM023F/fmp1y2+d3'
    b'qLs0vPjkJ20eI+cXTaIwH5ZKulAPTD1rk3C4rNNuOkkq5HzYok3S6XIdrUPQMvLHSz9GttzAKyUsS1qVewEoci5i9GZ/3pRHPZkP'
    b'X3kplb7PfukNA1LSgI6WuY7a85A1E5rT6NDrCp97v2whHWjt4XWqLLWc3YaqISNefq1F8KwpYdhpXF9fHBcqf7aMW1O4q9O4/mox'
    b'3dZrVcjoOqRdeaaTUG+5NLS7xPldIDqNpXs4tAdxGu4QVUHLfoPpLh6tg9X7g3R7Gam8Qzkrb9/RN1vv0mtELuwUlGZV0VzkEVmk'
    b'0bzXSKBKZ/OD3HIRUw81Dub0sJT8nYbdbmDPw3UQ5WX7CTBaBxsgFrCv9BkwDa8hJWC+qChItK1DWu17jaX5BXVwbHd8iPpQSJr8'
    b'sk3itkKgGo3IDntRi7JcM4PQPRVIti95L+2K5Ua+d1/wZnZSkqFw1paWDjRxEk5//Q5T8JSJljpzOGzzwYbC0FI6JmPy9BQCpI/I'
    b'zLN9ruBaJWsgZt2G3GEPW6JerGx7nJRMjLbdcHOVue50HwjLPI1pFrAdWxS0XAXzabwHIJlgshnI/ZJUtoURlUygQhhoHdbPaI+J'
    b'8PHjYrfd4FL20kE6ttF7k0xMQ/BkwKkXNAIj/l6IDqtidsLMA02kv8+irXpv3GMQIxpOlNRuCcv4+7ypPqqWLFuChEHPamGOhZbK'
    b'J3Lay+Yl3aWoyDdMG0t71U1PzOdQaylWqXy0JFL3NSNqsmKKyLFdSVMrdmw+SuvdaOwXafujU+SdNtfY/lyD1LzzPR6ZenBN386e'
    b'1Lju1lh3r9bAT6tPWg6hXdGQpuEdFYfQHb4XsMU2TV1ILvG3gdV6HE+D6zzblrUT9NxtWiOWLQQiWm1hmXvQKohPLPFb++CyPZf1'
    b'3Vfqua/k09rfn5G9q9xTb9XypBpwFFL1VR+Rb2jSkPaxjp21UY/dzyYdOaxzw5lNgNd43oDtqXR5tuNWscwjF2Z0ySKCmP6IGe1Z'
    b'FtKWRRvKNn6l2hw3hnxq1hDG7c7XYTVpXwnE0aLlsWs6eEsr1ToARGc3+1B6VfRdVHSMh53Y6rn2qwYMxJxl4IPYA6N1Dv787nuY'
    b'a6R/QM++YGPJEqkSdpcwvYeZpdNFpp21eup0W9skV3eiHsr133COnMwOZ5P5OfmgXNePCDg2jsGzEbUrDFnovi5rkj7kTD5gjVTu'
    b'/r/aZhVL4LCi5K/fvTh69fLD1bisdimEylbbDX5gWj6C6TOSEjJmcFjXdJEXFGrdo/GQlFWSpngdgs7k8vV3JCQFDVMCHprjKh+z'
    b's0jQywxd0MmQmwceszZKVIX6rDB4vkGFUbYcM7suOSJvXnxPjsj3+L9X37788N0lgZy/5QhjbAU4vs8kWW+K/DNMCBwEwygqtmFa'
    b'Ek65BB5M8HG7mRDyV0oKmu742BzSJsxoOsaQf3RpHS/SZIPAzCkTUayXhHFMY5IwgeIx+TmM40D3exUNfyZDZTcH0AGADjZ5OSJw'
    b'wMyfODSw61lts8TpLcGic6ycY3Dyi4ADA7gfEbznZ2itedsy/qVPyfl4QG5XSbRiel5SrYp8u1wxeqrCLA6LmGg4EZDgHJJNssEs'
    b'zqyiLlsLLq5VbVWDTkNfhZeb1FHBwrqBtvHeAHTRFeiiB9As6QbTpoYGkMtNN5DLTXd8st3qbiJpIFVjmPEMxpnrKO4+iJeqm8Dj'
    b'/dZ9DX3BZ0kP6FnSf+7qOHaavHN6W4i7B/hFD/BMH47+H7t8F7T7sDm+IjUpJzWZa5NjAkx9lOesk5tVSutWVkXOkhbaPWdOV87M'
    b'/gzGJnljYMVxYH+YlA9TSOYLeXWyUaBM+S0lcZ59VZGCggMFhwWmjHG0rfAmhOxVxJBrSQl0UZJhtcpLioFf4HOuAixKcivus9uQ'
    b'hYBDIrQDyWLxaC+xPvqFwXKfWMgzuKbqITiet/nCbr5obM45nWwtOJ+3MedhsrHgaU5jJUyR79XFo+HIzH/AvT9aBaoX4QYvcyUG'
    b'GWAOCYZgjuE+I2//+MqWhXCuhxyW4gnQipbkUBNfpERzSISjlXR3LFnqzwJ0GmxL5cNbmF56PdNdHxYmVtO7DYhuALbiuG11kKnt'
    b'6RkmpnyVwOXEzIfjHo/CAPNS4IPEBS+kP/lu6YQcz1vH6wfWPbSpv36yw6MRtL6yj3GiG2qoGC5jxrmr74TvKNlp2WOke7yrsaKk'
    b'vjxDyrAVAQ2TP7VWvA+MVr0w3ypd24DBcD6vzvoD4rbt5MPJCGSexUFMi0RUTpFwOnlA1e0CTMI9pO4A/pPmtjPZlKtr6/64P+n7'
    b'uCcveESh/u5GSQW5b/sFoN8Cb158fwQvUjj3wKxZjPVnCg9cUq7CYpPuFC/Ht1FKSUYhLgyftYl47LNHtFgy+ff/7f9ggfBpWJZJ'
    b'RF7tsmh19Oar1zRJWVAkKKtv0RRTyothIF/BIb5ukyyGogt5ATJHqN15E0Iu0zLnwkZJ4A4p8R2N+ndtda9fyjdzmIKFZkeKbYaL'
    b'RQ2GXDFbWpRnJc3KbckWxAGBX0aFEf9rEpbsLlyHmFxSyhWCYtqlP5cx14h/MnZUNNV2XOfEQ3P85yxPvJ260mikibDHZi0pkHE2'
    b'OZNO7XzXLYZ76Kr0sfXyKfx74kqp2iTyDUqq3e45+RLTvacdZMLyu8O0fLEdaIs+0BZN0MQ13ClQ2HsDq+vFeLM0XGpntsd1p17G'
    b'pWuK0l17mRJ117vaIsmWbl14uIGAhmPW9UI23t373uqLewAxqNv9bJCre53px63vrdso4ckL8V+rvz4+J3/BTCu2qpoMoxUNN+RQ'
    b'qn8P8T1UgLr44EvosVnqEqZQlKrqbUkLEtMyKpJrGp+TkOU/I7f4LH57pa5ZyKAAnoEw1WsKmaCpvD2P5EuuYC9z1O6GZUVBUx4a'
    b'ymFwZ8JLHoZnf63Cklxj/hcaVjQjYCo8GKE+HG/yVVhgIhry921ZyVs/LOD9Cu9yRBtlyYLAKFnmKdgJWCaXGdbXmxDywzarSqG8'
    b'51AgVzyNmMGxJMtwQ6I0hyUOQOceM2kiZMlyxmEWj/kTLsrX10mmjOCPWTYbIXOIvD9M8bDOY5oyUwC7tNEfAaSFdk2W47mgJwaF'
    b'yq0dbn1W4bXFA/FUhF5A6eQOQHmNZW06rMZ4x65mglVmMu/Y1cyuarrHnU47ALG7NKjunFK3vcFDodh6+HY52y4osCvgNmgGIUBO'
    b'Xf8dgJsdrDgh/obsBdArIrm5BnrBtIQaBU0omICxZrQsz1EkV8ofFmAP1E/eXh2MCPyfq78cMZMY+5NHYZG3V0wOFqDuH8vNYmv6'
    b'hNm7SRL69PZlRujh+6eSIezld/uYXAmsR5ARh1kMgVvj8ThX7z3OUfOM6f02KWXGSUbAIkASgWw3DxFSr8vDPRDiF/b7YXTfrl5R'
    b'5577Mt5uxvjyHOOOjPHVOYarF5TilKwo3Lr5ggzeXpFyVSTZDdyLPCHMYxJmO2cT2bVIY/YejrZFQbMq3ZFryqQGOGGn81s8luwq'
    b'1FSANQ+/ocPE2OsOKnn5OJL66jAW9sn3LtS5PRNCAsTEBRmqy/obKDM/O/WWKWGpu1A+At0VylcX/tU9cceRKYVRkgnTcyXGbEDh'
    b'k2/LdEeGoNshcXxArrcVyfJblI7WEOHBvHw5lNmaHJHjtZRCUHSCtw8U8RNbNiJJTMM03bG9ksIYh1HQKA3R44/8eHk65coGPimZ'
    b'c8zcKSGPAJrnDc/v4VBKGb6HOjnEVMpMlvA1EE5dWl5MacqDeA8a5BkF5lfd5oHmOmFM1nezw2CnDfP2yBptXTwXfFsXm+Ac/IDd'
    b'I6/IjlYkrHDnsPW//6f/DPwy3TEkkDmnbL6j/xPXRR0RVuqbLJK0gnROKOJ+zpOY54SsinDDNVpRsV1fpyjMa5TMhdi8CnzKRgPN'
    b'/X3pyHNY9PSU77GLJRgXpWFp3uk+oOUO5xWJD8g3oJiqHV881RdpjuHJw1pEPHHn6hfTeEi8J/GaqXUx3WJ5QLoUUYyP0rPOvkHd'
    b'VuC6pkfYO4zMrwCoUc7YLKJP54bD2wymQ8qOBve77laKZpVDdzj1lptexgvDArkHiBaPwv52hXbbAp4qndth9DtM9ymQgnG4Dv65'
    b'qpqTc/ITS1coMmbrdm2ZKVd5MxN9YQ87p59ALbMGry+ojQHlmQmrGoZqBtCycM4vpCnGr3+8LFnWehqDvx0HJt8/zFLCk+L+iYTL'
    b'JZ7zz+DBh2tJSkqYQ4QYDeQLTIEfSgPJEoRC+FKtKMQ8R0WI1cKYLifNwQwPMsPRj5fz6XSkho+TMtxs8iTjyRIea9b4Ik9TlC8O'
    b'JoR8WCUyz7F0DB+LHMqgwcm3hSzdyGGxbKD8clI37h4P9ob3umg020PRMGvUNDCYfVUBVp9G+EYMYCfovqjBVi1GN9TYXZq0GBab'
    b'agfu5Wt6RR6DdXYAaPFaDZR0Ce+gW9G8x83yQOix3U131lweigHqpElrKBOlhw920C42BRt69xOil/jdp0ps6HKOfnq1u8IhYe2b'
    b'K5obHW361D7W/e45kPq7w1qTFNo1vzdNkn9+4RXl/adJJI1PsiqMTMw0P4w0Awo2POvS0KS/zq2bYUPI9AkXoqUE6luPc7ZbJ2Cf'
    b'3bYO2gllT4t53YSF1G+82kXiaFcv4ThE2o86881bo8YQ0g0r2eR96MpHQkPeZScqx5DqfSeuq5HWpuyGfuifohJHGWTc0M2YqkUt'
    b'nc27NXvWYrHtFwj4qKeU79aBCKHeQX2mowcIAu1oOXWfDl45+6c6mRe1Bgsos0xuIatjqCmqxpwFggzJpcOJXvAto1lVnpNheIAh'
    b'Mqz1EdAZE2WHWxAhFfPkobNS7cVhMXUiSJpQeVf8NZ9O/0SG1wfKIUjKnxgDRobLcMPUnDKSRuADpVA46CiI/okMowO/Ek3AZsu6'
    b'DUuN69tM39GEMWEVa9vNp38AYVoI8QgthfQEcGMBMI/GiVX68fEw3nM+9XRlAmV9X3nslJDuXMtDnZeibqqB5R2SocvcsVNzH4e/'
    b'N/RxVIDkCJz6zVsU9hT201qKvEi/qdUwyikZN2R7e6ndbMJR3dzxowqYjeSB6WD60AjxiaKjUWsbeKYZjWqowWzkYNhO8nIKHNoQ'
    b'JvfJFKHde24VAbj2fMhqMnPzQz9+iH+mCoFcHn1Lqny5TMHf4K/AF9/+cPn+KsD/nQWXr97+cBlcvb789tXVdxdTiFzAp73yR2Dp'
    b'7kkZreg6JFxgArb3Ky1y9uDX60WwoEQWAxHxagmPyZqGkL9JzOorKOIN6powRcVGkVxj/SQocSccEtEpBNn1Ykmq2yTirO0xeZlV'
    b'tMAM6RU87iMIBUSmQoZ0spyQnw2Vzc8j8rPpofrzAagrODDQK9KCVfxhHiRQduerAqIIx9uSxlgVEFM7snpGSSkLBk0efN+SBerR'
    b'N4AmVtY7vE5pPBzgLzM2/8GI8Dv44kOxpVo9BNBDBJuZqCE3/O+sbIdVfC1Z6MioKdzAzjNvJ2odsje+XlpHVqrslUapxUXUGwHe'
    b'4C9qomRop+bq0KXl3bzLQsgE6CmPe3/gXoVFC9heLLm1dBKv4bIO75L1dt3VQKOfmoKmichC0DGJmlrBdPIU1N9tZKVnbX1M/ixc'
    b'EUpaaYXG0WWMZuPrcLlEb7mKnTIudC2haGwUbty6Ilg8caBaAC9hv8m/W2qYHBwc1NQlgeouGmSnYgrGW4txao6kMXdetMIujSJA'
    b'+IpTahsxo2dcsCnXYZoG4HPHXo0y6MlI34tdZxPIXjTUpjEmXzNR6Bg21tSLwL8nOk3h573CHX0vHkYCV2/fY1iCEZIGb52IR63x'
    b'MELdn/OaVtLRUTpCpnnGbj1494vMj718U7ye350gNXp9G/KdfN1o7PWjnDELbsf/C+V96uo9q3oBeHKs2sq9w7Y6hOQgnE75GN2A'
    b'Il9+I2AVrUli64LyfAANlYb/RLQoRNo0E77q0Z5VOTvt6lD65tqr1xb8iIGbWvFMzS9I1HkXB0SLyTyU4Sbs5QZQBP3+el+PL63S'
    b'w3H/+in79JN1BXr2sypCmL27X84G+k53D4rB0z0xeLonBnv289TU2AeDj8n7LRTcHMcUTLDA8e9254SdABE3LIKVjYK0GFnGbkGE'
    b'EDAInPXcdyNa8142I+f6M1MB98uWaawPHnm3fDU1STP7oPlHKLo4FgZrziuu87yssEZcnoG4hepFLM8IJmHJgEOeOI4VbhT1aqCv'
    b'deegFqIm49yhSL7/ALl9DaDomdOSAVlCS9abbVqa+ZY1udSQYVm9B+NOnd0/FHr69X1rjAAAk3F74nZtzuSCqE/C2GWhNVKIJy66'
    b'uTpabZrMvhaADlnH2oF4H4qeQKxGILwzlqOFVBp7gqmtYNXbmNFWqddj1wCgPr7qoTSXKfw3lFzSHfYeaSGfPUyax9NukXYN2gOf'
    b'HdNmfdo7cIjJNGU1lxaHkNZCz7XPQv7Iv4VLV7gPdrjIxx1zV/aJ6GBxXL0EqUZ1yl63dlkV26jaFmHK60hfJ+G9o2PqC0I5meNR'
    b'rdN8C4TFZo/ij87C6N0mBz36fngCKm+pAu612Tc7bNaeG48Fv6XkTSP77Quu65XZ/uDsesM8e4hr82mLyNF+OXe7V89aX+LIQNsv'
    b'tw6mfSh2AT4GPO+yVw76F3L++lL3znFoT4DTVGTL45tyz2JU7XqZmrKZnjPQIgvfq+ZXe+8ORbOe3ftotFw+LjTrlu1J+YbSoGdf'
    b'Q1GxVwoBl7x3UYoMUQRC7E3lDZfjF2X683vmdZ7e803ZDqDL8+rZA6RVbj8MraPQjBbLXbCi8VKXLFwoXvnqIRm3pwBJmGKd4IKW'
    b'SZpgosX/igTcPrns/tXCcZx8TmK8PmSd9ubZi/abPE0iVRCzLUu7YglqIMdw11BltdmW5x2SFRGtH6254OUeA0qvmtPx5YxA1p5z'
    b'Atov9rZnB4mF5oBn3st3wTFYscbTyfHXzzA2Mikhu4kIgsH4GJVyCysclJhphNU+I0PFu1UxAnYE2TAgoIvAlbKCWndLZ6V8dgz8'
    b'iP+1SdI05FKOPFc8kehj5iaE4be4XOY+BJMHroZTVc4/3D0orEiZb4uIgusP3E0iBElbjljqmBdz2JYQKhluqxyevBFG/mI+mKnh'
    b'FMRmFTAPmNMgnAXRYon5t8HTKs/T4ZJWYVUVUOsDrhTVMC5yLUJMpOwWXjWDEWEuzgdgugY3o6REozVUTUC3H/bdGZ+hQUyhzlmn'
    b'YQaaB49vXYza9C8gm4nxppMpc23xTwjnPeMuh3AKbOJk970f+hNTEGg3QoYJXNpFqC4Qn+q5HQ6rc9oBVLtmhR0V7Urbz7zqvx7r'
    b'YLkXlis4eAuKtHREYc+ofPlg82bvO6ta6IMgFxarV0R84txCrpChOVHoyx3pgCBxn3PPeIR2q/AjL2Sstz9oEZW97HYP7Yh7+Dxe'
    b'A/8kUbvP07R1YTVigksHjS+odo2JTW4HX0rIbS1R0l5DbN277g/8ooiOPzsgN5dRY1w7GqbRcOTUBD2wnLVGej1wezyBXGdAuXg1'
    b'8qSg8TaibYYKl8VN8ADxyhf6P4vz1LbTywbXNtJZRv2IipN423xSxol9y6wr5Aq+3ohczeVM22QvRYxqNk5UejJ9DfedNR9Qq304'
    b'P2Wh8Oi66JuYBUHToWlQTk7V7e2poIhXqLcouOQjfszagwsNh74AbpI5bbpkjHLDB9qcfE9f+5B7jxWcAXcWpyYajRMoB7XuLws8'
    b'AxqU6CGn2aX8e6gxuoY98rcykeltY69VIyrjPpUhfn6bWg39Pelksui2RBuYq+vtggQHSp1KrRO2bGg1UgdDKjkC8sVAhKGfGi4I'
    b'4wM6q1DfO+6K84puaO55QtffblGeglFO3RmtO6v4VtO++VvV7Iu3sR/trClDvmqbhteQOBN9k8OiCHd1yqiBtSYnpkKuw/liz91u'
    b'YM134FcLIavPr/9Ooxpevw6rIrkjFyT+aO7Sp0kIRh/T77p+r8fZZpJkiwPeeLMbNsgcFTjExXcCgct1eDe0pzQi4V1SXsw8fcmF'
    b's4CPCCjMlnSY0mwYg3u6M569jSWN8gzLkmwmeOHAZeOZyHguJ/PxHP5kgOKPgzhfJ1mYVYEGVD9E/LY3ZmJ70k8KuknDiAoUyrSR'
    b'vseJZ0D0F4jhzWgx1JrxydhBQe2UPoop8bl9qp9c0xTxvNTihJ2mj+521YixjJzZeKukRJtzTDcgTKATWnskRyC6/bKFZL1FGYSf'
    b'wyQFxY2I5XAjUY2hmoU5Z1b+U8GFtjnGwBzhf/cV3tI8WzJP7u6uIPsazm3Ph2ee4o79vSOaH6YOvI5GnBpvXS6D7e+0y4G0ziKj'
    b'VSuU9rXU374OMHQ66lt0eh+TAlxK9K6iWUzjBysQX2Mf6mE8kXW8H7owfPxxgIcMyky2+wgc99hTB1hf7dA/293gIfwE/jmW/nrT'
    b'+9k/x/TOq5T99OGnd1fkry9fv756R96/ePPTh3ORkxYSo7FypBDBXOU8jI9k9K4i18mS5w8DOBziCzDXbFZJmpf5ZrU7J4Pvt2BQ'
    b'IM/J27CsBhgWxt8Wko1zm8+I+/LwEAIOcQ0QMUxsA3AgKXMWJWFK1rQqkqickO/FT7I+2Z9YaqMjVbNmospnwXQCNnEgoa3/xWe7'
    b'Sqp3uXGBjh4gNtPMeWOwE4zcJt+znNbjNM8hnfC5whwUfkMv/0MTd2R4evqHA+hsseD2M9bFXa63c0+9d7lxcO/tLtfdX72bz5dx'
    b'JBs9zYyWriu1Z1dFblkjNmZ4PPXsWzcENdzE7jRbmWDDhVKDn/u6KHYH1uKmqHD8IqzCdFdWJRnOfAdCWpkcGdXf7D6eNQagesdG'
    b'Nfm3yL0TWjrTHgt68Ak6Tst6b0P4V+u/fQu5b9OkrIJFGpp5vHhAdpVEN6Ad0J4bg0HNw6isCo3PiScM/Kp+LKtignHpQ+3HpEyy'
    b'4W9lVQyrA/GVRZdDgHa0WE4WebQtAzVdNq3yd3c4J3l5/HGg+gnpQs+Tgj3AbD9R7fj3oIzClILFz8KUaaI+49cHq6Hb5mKCjy6w'
    b'7psiwYkOpJ9vjw2Se6Qnv9KgBFu/yBTR/GAxm3f2uVEi0mq7RF2TksYVkhSSa9vrV6Q1Ge2LwBCejrHz7vNhl2XTZcr/M0sD79qK'
    b'RrZRSKabg/+1bROmJdaU8U606Vr2Bjizp6fe2eJxPta6Mg5YrpKNVuoZWp1Na4hJIds01cmL8EADbzZBwCcNM3vWH3+u9KoZwdx1'
    b'+ywPmq+VH/VTE/WnXfBXswHyfnLX5u5v/WQVD/DOeHZmAju+74xhNro9yUWID+tybMP4pC1DiWT+ZZy4eNuT5k/uRfN8jQ0BrbhM'
    b'21ZtTsFiDhYhjwwzsGf2NoI51Wqubxb2picPSQTq2LuUaxz9NsJGMUhb6iNH7m4kpfozYTw8/PTUk4c2kMPJvcnh5L68rp4o4o+D'
    b'Ol9J18MHwMQf6+Vr3dDnMV7WRF/ovXTOin2a3Va1ng6bw+4NApDW1+Et2Lf+EWgYND2k9KQlhlJfsH4on9S4KGqb2SxFag1rxZsa'
    b'DU1BIQsaiR89ehTTBWYE2VYUvSETLWOI4SxbDuPFOUjk34VV+H0RrukBGT83fmDJjMC4FC8mUb7ZcXk7WZB4QtebamcmbItA0n77'
    b'8tWry3fB+xdv3l0FL968+unH1+/NRGXxx4gnsMp4Wj1zDfCXSCfFsie1ZY/hTQNIAGsVQDMAqT8ECltAi0xSHKIyKk3NUaCmMnTf'
    b'AitqyZqETRVMH0iG5ayEFDQYQCFNOz3qsZjJJWxAnuLEkMKME5j7DkqyMoE39P0m5AXRZyoM2zSaHS+Y0gFlew6yFfcmSqA/nK0k'
    b'q+CEQElZBGNRULKoHXCS5VUWDg8m5XY9PEC/BUXqe8+Sd7QJBYoLSTLT8cBs/fdARH6bcSGhBQHuSF0wsMf89J4GBtQJ1jEQ07QK'
    b'GcLugwcNTGnAqUVI3cBd0LL3pN3+XaiENb83rdSBaUHRfpSz95zd/h2oKMq3YPHvNQKcbrC9Y1+7WqZgeGBA7Yty2bETOdaN1Ijk'
    b'vadX0ihY5MX6+ORUm2ITDYqhrre7/YeSne31a8CFS6UEP5xPQCdWN4EDMpYhJqJNdZdp08PMjbNN10tOnzAAsgjD63GpXfjm7aSS'
    b'LnewSquUeDUXT4352NfXPXI9Ouvn6N4max/3uQ9W6rhuj/XVcaUHXiumA1N0bKuKmxEjlcFNRMWnwTwx/eLmc/DE9DK1+umhW4pE'
    b'Wh2XqU/RiH4HTn/3dDckefTOQJ1rXzSDxIJfzPUiwt4teH/0vE9Z0jdu5fVxtV6AVQ8bpFAY1NKYpjeobaMBsWnA7G5/bRjdSHjX'
    b'ODrfIv3+qqFYo4lnjxr8Y0wkeuZmL80zq3oKclo1Tgl/cl8pMuFh7bPEmlLb80VN617PJ0VtulefIcuImdfKKzXIrJNreszcK1D5'
    b'p8y3TjhJ3s8dTKZAgJA999HbJd92LbE7TbyU1/cqEkdBPQuRSnXlkaNefKZsJ92TwanCqLarfiufcJ24Gy7w1rHqTnzvUfjdLAer'
    b'O7ytYPDu9t6hrQD2y1cng5p04m8gDt1hyaGMe3ntep33enhP7pmiLAo3CSyGLhZJBOHLuz2A8MivMP77tqxoLJW8e+db8ydQ2dP3'
    b'UynFH3bHOvtZ7+Gs0x/5e/dvSR/Z6rJrdum1M8IliNtmHnZ7/P5GfRBT65PVA0gbJWvss9kfljk5GhFOezi16wVD9901NwPJ/TfL'
    b'E2c/6ttbFY9CIyfePgXb/T2gwenmhwqFgftBK+k6KTGq7b7z0iypSXmTLxZ18HrtqebE+LAbW+9Q3GfpTd6WfQ5j12CMBwx3aT+T'
    b'DS7F+8qwjglU2P+776orMdbLPq7AiHWBnNq0o5YR6m7qh4LfeN/UDOLU2msbpPH98FCD+HhwHeyeoGtZQf9d6Het2DSre373IFwX'
    b'Vy2HoTWRWP3z9AEOyfz0yx6S+T/jkPQ+ifscktkXp+TmrRBJNLSX4j6kXue14lb2Bff1NNw9rMeK6XBiF4Nt1bbaHdoVOp5xZr0H'
    b'mu05Eitc22ek+bTrSHYJ+A4uO2aHzuNYVeM7DGT16DwS1PQt03xDA5nXEOoPt4ymes3WTYUB+SBBXkj5rQtDt0jOPJUOnTR9dqrS'
    b'2ltif7XwaH920bUPR1Dlnds21g0AHpGx3D6trDpH7VArHc1sTGClxv820IIzQatKeNeN27f0eOfrt9cAvOR33zFMcrXGNxG+l7Qe'
    b'Xpd5iheAp27eXk9pbzmPnmqc7sHa+12BPLrwodbcUkLli+m/jL4WOrQMC/uHWu6DXV7KS5T26oDbLtNsrRTWfBhl90VBy1Uwn/Y+'
    b'iG35R8tKLpmpCvQg4s6jdHmwe8ue9dqfsOJxzrTabu5d6YRtSFzsthtEbB8K1iaDOXvrtKXdlyduwgD9w7IyKSswK9y/2rJ9yB+s'
    b'sLHFAL4IXGAODwWYc/iHBNd12T14fJnMTloFGmxluYAUZRJkeRWIyF2QY3hZ3yGDOibP5izxzqzlcGvzOjvlQZfXwea6dWLYyprY'
    b'dZ6mCRQQrJ0eg42+dadM0oLnfb/pSUaZp/A0rlZFvkXR8H7i1n8UBtxCrO419FDHQHH1Bz4J10V+Q3lNi06KV/tN/g3mDG9RfjgP'
    b'7P694GnZpZf7IO3Qqy0tdQiCD95UBY1AA7UHhfbim988LN+8N7ia6+2bB6LCsOJPFRVi3myVqIrZCcsx1RrHjmKMNImwVG5tZD5j'
    b'7oq+p6WJttlkChJZjVjhyNsYh1r3LtOydtXwWUcaNHwqbdHNQIWOJniUCzqd1wmZ9kVnN8KUt/5LZx8KMHdJqgjczWORsogjjXNh'
    b'Vg0IYbcpiS9cToNjYK6nxBOYOOWTY5ogqfJ0S9AeH+t491FJg0MP9rXfmEYTpD3n6W02gdBRzQnaQV79BLDurPUMc2O9bWLSMANW'
    b'C4kc3+LREuL70Kbiw/hUrl8OwQMzUO9PZWLx4s7tKhGouvpx6nbl2FEdfeiKPw44CcreevYRnTw7rFueeM9eIjzP7+5uWOvQ/AJN'
    b'csaIe6CypkXUHJ0T9+jIn2oJZBOWpZ2lqwsdPYe7+ymXPuHfH4mmNXzO6t9Mzc/7v6c4b3LVwppZBDOv3f/fI1nu54QM59P52Xh6'
    b'Mp6fHpyTH3bXRRITTHuCKdc2RR5v8Rokt0lBSb6A4OwkDisaP3pMLpfLgpbgdEHKKMScbiLrW5JVOfkv//f/+V/+9/+L/PiK8AIx'
    b'QEqTB1zHeyzNU5JhlK/XSUXm9HQRzb4ekVk8PVk8fTYil9+9C96+uvzbt2/e/NvB+aPHhJDv4SnFynNTPTGNvGE+nJDD2fQPHA/D'
    b'r6fxiMxP1jm5DqObipbVAcL5MyGrGRqjSpDq9fpF7N+bzbYkP8zI4bPJ2VMBbjZfk2F2MZudfD0im2+mk+l0OlMAzwKf45sB8Iwc'
    b'Pp0cP7MAPp2eeOBBpgA6x0nSO5mDSC50RsbzyamAtClyyNOHCcUipJDT+S0BcmfwfiBQGWlNWYkdFk++SRNaBE8YPPxaTnbhOuUl'
    b'lqI0LMtkkdCCDGlYpLujyWRyFNMwPnj0GCgoTckC6CeEBIB5klXjJBtXkIuhDBeUDLclJSBQPlmTTVhW/DiU5JBE26KA2Ja3V0cs'
    b'8+IBUNbrHDL33UABpmFBGXnm2WQTVhUtMmZNDOhdlG5jWgbCe0xAXW7DIi4Jc845mDx69PaHy/dXs5Pgh799++7ld8Hlq7c/XIow'
    b'dpn0e+AlJ56+elBDI/Kzf8fFZ/8Giq8127EpknVYtLVah3eD0aNPyFjer/KiGle0WJN370lJNyHP8HRIkBLGKGABKomgIc46Tsez'
    b'Y8R8UQYlQOEUewQ/oH8S+7vcpEnFim8VSQ6MIoPiW17UPXrM+AeIbRuQ67KKyDClEipxlWq+eH1BNS4yfPvqw7txWe1Sek5m66Nj'
    b'WMyjx0SUqSK3qySl5Gx9BGemrJI0leLzAavQRe82aRIllUg2WYTVihaYSPLRYxJiMjRImpJvqwmbBBM90SUAHM/kEVskBS1JnhnJ'
    b'1viqx+s8q1aPIEvlZ1oC9IqkYXSjlWUYM4cnK80f28lVXiS/4t7gbo53NCzgkBxMHr3/4c27D8G798GHd5dvvYSq7ZGgD2OjtB9Z'
    b'U4lfm/ials8JCwz5QZqHMbymAoqldSIqDPhBSpdhxDPNYxa9OCnOyeBtWK3IPzD/yoBc4H9Hj2qM+4PB4FUexkhYcH2XFXl/9YLM'
    b'jr8nh5ABc01OiBhXXk6YB051gHUn2XLCDE/vIPEnqW5z8uL9X442YfHLllZkkaS05Pchjcn1DgHAUJtkQ1PIeip8CfJttdlW5REs'
    b'2Yxc4OMf8f8GbPzJb3yQUVR+/l3KE3D/wjLWYRYugQaLMII8nvAyiQKI4OGpvtNdUFDUXk126xRer1wvZ05FuZb0ngbHI487gJnE'
    b'ciIQ3XoSxGHinQbHKOOuIZGbR27ojqHxZ5Z372dWNRCQOj8DvAZXf3n53dXrFzJrCMvF+mNSwhni+/Hv/+k/E/TjIAuEOqTZMslY'
    b'Fb8xvEL0soMHE/JhlZRkHd5QVuYTRuO0CEcviap0R15dfrh6/2H85vWrv53LG5/giS3JKvxMSZZLkvoTwrkN05sxv0sAOwmW58og'
    b'dyIpKZ5wWoqSgiUZhp/zBGgsLJa0EvcVr1I4GAzkeSAXBM7CUJwNrOcn/nCL+mHbAd9znkIyCrMY5TWo7fCb3FUzpGZwbikhcPAj'
    b'Fr7sJeEBfjXph5OPVdVhL1BR+XkvMHAqHmA2GhhzJppSQblqNWLPOXX7Ya4TmGas+UGw43vPeRhAvBhj/AQPaXlOIOPRR52Xw/Ps'
    b'I0t5hJmDIIlVDnXANiGcOsjYKel4klR0XQ4PzGRDG2iErc3sQsmCbCb0Likro4v4VxWaC5j+L14YL0b73yaegLNkwDE23JgJW50Z'
    b'lNvFAmqSXJCBxHJtDzzMYoSo/DzcjLDc3Jqu82J3wWp7env7f00WRCRdBSyhLxzjRJDzGXhIvLDd4ex/bOuggArN4mG8cEeidxHd'
    b'VOQK/5PkmR8WvMadDyhi4K/JAufDCUU25I9gnWSGfA0XH8XaPnHtGS2WaH1iQD5OFV2xSyLJxKfZ+Sc1huzH/s8E/zPEliOSZxcq'
    b'b+0qv70ANot/sJ2l5QUmsR0E8XYz0FLWxtuNrBAUqbRYfAyxD1CmdUKzuIRLcMiBqBRg4K/I4ZhYtecMVVklYkQXQ4/AGgrRTEpk'
    b'RZ5X5bBGBkPRq9puUvoRfh7hRcMx90DXFO8wyWCD4JSIzw4NQLMRa7wJ4QGIDVhzTMUMCjDOsQQQHQFDvWmy0HtKPsHmCT8dsKEE'
    b'vvBECum1gmjaIfCcc1xTjYTKSRraeRiRj7KFc5l2HIGJAABGbRPUh7EMLoqfmKShAJuMCibqGV3xGtxhP7upP+L+ZXCsZXmxDlNI'
    b'vytQh6eKna1OLrzJgh1ZxqVIXiiGBrgVJ1qcp/0Yh+QZuqtwrFphRSn5l56LWk9Bjf8fhMmNgID99J4ZHQ4GB58sj+RBWAb5IoA7'
    b'jrFpdzXYQtYyg5agKcFiZqqv68U9ItsquvhQbLVbI1kwaDIlUJjt7AuSzZw1o78M2f+BwlYH7uTZ5a+izINFka/r1sHfXb6F+OF0'
    b'WxPOdwIKp2U25OJIUOZFdcH+/8EE/mBKmHIoNwS4ttZYkIOCiLWu4y1oBqCZlsH8htLNxSCFEhUHJvP96IUJfOV8L+iGLnhSUCiM'
    b'gFatIfTniODnTTIoBMQS8NQetiSrHuaMsZB//kciRux3YGT2Q7hLN/Hk9eXBJNtmyS9biuvMQrZSudTbIgGVPUimfNErGqbVSufy'
    b'jDuDLLkDVcQ5iZOo+lhWxYhcZrtPiAW4nc5dtsvcBPUbA6TdbQqBq9fbJI2DNF9yWdyn4GCTmfy9zDMl7oHuiF1dk/VNnBRD9keJ'
    b'SxsRvCOC/MYibujFVlvRu2oIICfxdr0ph3xdLIN+Vl3MRwTp/IbuBExRlB1wTw7J4H/JBiNCsyiHd/zFYFstxs8GbTweRTeOd7Z4'
    b'Xe7HgxpURZiVzFeubL8aK6iXV3epSt5S3dXEanTi6sZ+whxJledpOSm2WeB90ZBkDbk5iL5EnqmEPCZAwuckWWagplSMWct/afG0'
    b'6o5VPbA42kEnjiYYvuzM2O8kKXOYWFgNUdZSnw1uzsQYIG0bc7VXsrvoYQV1C2EeF/i/IBvkN6AXCeJwV158PT3YRzjwbZdBW+oN'
    b'ziiL587oQFWiZRfaEm2/JIV59QwmlWGCz/1pTK7iPxylqYXLRTRS23z20ORWq53uppaGNk/Yf9ZJZpwcUVHkHG5DckGORZwMNFQL'
    b't5vNoFmLtrubitur3v4Br6Qduc2LG1boirViClU0wxV0QYuCxhPyckEKCnWraOy0Y7SfZDtuVonCLGfVpd6+/EDisArZVVaOCL8s'
    b'Ud8qzHZs4kewCq0mEh4fBYkPlsUErz4SEnajEihtugijytSZahc1DLrJxYOw7qHLPbMT+XJUnY7IANYQbJJK3O+De2hULRniARSr'
    b'94Hoagp7QWtVs+4LbR9tq2eseyhd94XWCaN7q2D3g9WgiVVHrJGG5ck4stO9iQxyeO24kzb2S4fCJqiLiVbv7ppixgpscR4WNOAK'
    b'5ISWg3Py2+8jMrjllbOAfD79vremGRWIF93kAvhX0pRGkPoJwJMLwhlVm9aa+f15pRdT8cqVS1CPt0aBK6ZcexEX4a2rzLXnDYW0'
    b'PDpupbiFf/p7E0asf4cqSHAX8gsQ1JjemxHVo3yjUOVlkikTPupuX00sgEsIJoYaLV0TYkz8G2NOcPfIw/JRzOJTjUmBj8Ew6zUg'
    b'tEm3nrFctDfjw9XMA366Pdlahz/wrrd5yw2sOPRrwnhubIZLzuzQf1Tn+ZOwSXjNDYvBb2IhvwsJpspzUq6hROnwN32w3w/+JInk'
    b'N2NWv/NJlbZ88vblBxfd7n4JcjAQ4bSyjo8xg04HtBPtqGMAD4BHNl41zvlJgTFuCfg3MMYfnJvzMS+vQZHfAt8FnRBUsmdkYLl+'
    b'c97JE2SzxvpPdnOFynwdyIUPzsl1nqeC4rROyqFBNzH5mKZp6dJoVqBI0Dgui6WBrYaQUR0Xx6oMQg52Dom/VzqpqkZ8kIN7G8NG'
    b'5InPieL/t5E12chQIshT2Dsf8gxzDLTjelHTmOez0H2M8hQoZcpzyxvGuI/6pulGQt8ccGh30E+fPunvWVop6Uy+Z5ufsi0vTu6j'
    b'SK4+fK8ULOJVNcJLdAWemlm1SneEOwIpf6mkmtzzkWY8u9QLwJKMYeHgJBdW4IbdR/jfE5ApY3cFAh/uPRMNiDmL+kesTheDOuDW'
    b'lLj5vI/ki6ItkJghTmscrF68NcyTzdJtf8nW8DPwXgBdeevVh++DH968+u7l6z+/r2OyGjdpbF7HVmrMLXLpNUyFfavjKY0zkczF'
    b'GFrxFpGTSfqGKrfRzvXDBoPBe3QFfveeOfkiJDKcrckhOV4foMQNcMnwDH6azdcHmvMv12L9FYrEg7svdL8twY04yeJtCRVJz9YX'
    b'4+lk/hQh6R+O8cPshFxvNU9khNfkjUyGx+vgV4henq+DX9lkwK8c/BdzJPIqh2CQ6VN0lqzyHEHe0vCGVDmJC3A9huGqvApTVMdR'
    b'dEucEMREBc6CcAhJCi7I0BLK1adE5rtAeCGUESdxUlZJFgkHZdCWZjEJyc/1/ro/c1/k2xXNyLdvPvzAVowe1ODQqbtWg/5PuksP'
    b'o5SGme5rDWvKaFlylR14yAOsF8KdKI5pLCjV8gc3/l2QX4cQBAkBJfoOzdYja8dMsa/hn95tWeTbjQOM/doPpJaogEHTQ1EFczEd'
    b'3but9Mya3Gx+n6Xa0DgC+sHUg5OstcIhtLfVoTNYLCtXvU6yobn9IzKFmtIjMqt3lNP/Ce/5FLTLlNMgR/A3ZArsAtz7gR4ZQCFd'
    b'GMne0HFq4XogebxtfCnhoD6m6TAP7FZVLWclyrVYLdVJ86fv3KfO3b4DABkkBn8wOMLpTKnkzIMGbg/mUdPVd77TZPcQ58nqpx+Z'
    b'gS9+W5MqEE3NM8VAOXPu85apul3keaidq+xjpSbRJivwKpkluPQ1hIpH7CmIF6raE2Ph+4CSONNnhSwGySTKsyishvZkRyS8S8qL'
    b'2cEEg8/5H2ouDgBrhg39/cdEzcuI/z5WMajHvpB57/GRM9wDVNOp0iJCx55V1CdYwCQms8kp9u+VMq4my6VX8OghUn04AXnqUgOB'
    b'sghLGQECzAF8XyfZtkRsQjweSlbv3vM7/C8irtOOfSQ83MiKgSQbWpBwGyeVCLYU0sBbkSERF3FOyiqPbr4q8V1DC7Qmg6UyKYla'
    b'Moh7GK5FnmNA47v3PBzitRBGODAXSEyjcAcAYMEYY4jSCVy4Kk05EeWVJ2ZISrxgcSdfeTfgKx6ywQQbMvx1jD/DgUyTzYbG5OP4'
    b'eESOP1mxGw9/CXnCC/teC0UZoBx70TNlnOiM0m+v3pj47VHrIkBU4BK2GOag10GvOVM1gZc9TpUI4BVgxghmfE3DCqntmobFmJcO'
    b'RwZaQMgPRkkyAdk9W1YosArZHREWFDwh76sCTmiJj0AY4qigEUyB1Xtm45UYfzkLrrdpSg7nT/8wIvPpfBpE+ecEjvCc/TAPAAAe'
    b'aXE83xTJEp8XnujtKM/ihAcAGxHVmp3j3fuXw9kJJGA5OSWXr78jV2+DDx9+5Pm68ReeBJF8A8+i2ZSzBRVLjiYHVr9ce3pjCqth'
    b'mIJaYIevUBY0HqADAhtQtqaboKogP+LsSATxbmjA3k15IT7z4xsnBYXYLmV18k1Q8ATI95Zk23xb8rfaR2Tqs8n0EwvKm0CmWfAC'
    b'RDEVppwqzJVkTYXiecHTxqGZdQM+C2E6IT+VlISlHhX/5h1RcblflJXUBSP3ZyZ9spidyqMqt625I2vGMyRgx8dgtUvx9oFHtWfX'
    b'k4WAHl6XIi5gcQstWsezgVkJzuiG2RkQEiY1O+KQRaFAPg6WBfSmAqIbKCUETBNTB7OZ8s582thZDcWjWTiltqY25nlHOco4zl4o'
    b'UsZqGJuCsmvwnNAwWmnnHZMcJtdb0K+CUkYm+YBkPEC6mDX35BQTuuG+ogh02pyGStAOeYynJgStz8uLY0AS/+P5BT/UdKOGMZAF'
    b'CUNE1jioB9A4mhzn6u3zi9n0D3ygq7ffXJz+QSJUDoSnn4wFlnlqug5LkuOs8/U3F+NjOdI6Xz+/GM+mbLCWEwdp+9hknsj1P5Ez'
    b'fAi5sia7QO878EwYAMYMzFjlkBeJQsZQxQWtotq3umvQSmBhXoNPpyfWLciC4evvweNAfCKHX7Ob7yQIE347Pp2cWtfjab/bUAsS'
    b'w1Rp+l2XbwKWfkKc4cnstPN98mV5fU1mib68nq+5CweS6dmYpUegprWvgUSDhxnHlc9E5wizTvxHP67PL2ZADur0CsbAJiAHU7PH'
    b'DF8dx1MjYd/nF3M1GP7yDQz/qMMW4WoFS1Bzewiu4E8q0ue5OSPvAQaZy3xxKs+FkSUEmAPLIFKt6LjKN1qWGX4EvxUvykWSsbwC'
    b'4kF5TrSBLvRcNRPygjMZcjIGR9C8IMuQa8pt5eHlq1dosxSnw8gWj0f2a3aWhWj7nDyd4w9ZHkRhFaa7ssK/Qd8YQCmT2hMu1u2c'
    b'dF1s5I3Y6efioBAAI/bclVlW6GQ5YfYArv58AiIIp0nI/8eTzbENf/MOYDF5V5cwh+s8pik8iGG+zHbwZR+tNYlr+jIfsVd7lQDo'
    b'UtthX0l2f+amS5YPJZ+WvEBWu2TN/aZEQa1drhXqFWLjFciGcJyAmBRxn3MaVlIjUPMOHjzGXikeKncPyPXrrkKcxbMFkOfw3ZVJ'
    b'Rerjpzz18bOOIqlXNn1+8UwTTr+5eDqXtjy13UNgsKdkrGigy8IEc9bvCYg/FjC+uZjC8X0dvmZ7erfh9ezYq0M8McaMBskROW4h'
    b'b/02MNb59kpb5turby5OGVqzXFHRUNHUJCkh0oP8Q/9RpLb1payTXNJQKH/UkDgyljdSI3/S9MzhnaFmxtdMSYvPyCDPJYf0cftq'
    b'VVA070IaLKRkUDZCv0ft7ElphU2CZolJ+f9VNwE0fJBLuSGdUh/jOlprRYoo/6WMKk831xS9AzauLma4YsMMFTZ5XSa54en8doz3'
    b'6BGcGHKkMIP5dsJK3ctRWEUrlg2HJ4aLbNmApWlDA/06KUtaGhmzQIcSXudpEnHZELJn5RmBrAF6Gi05p7zASdG7qoDMdPw2RefP'
    b'cRRuiHB9QXAbiKYUSYKQ+8kcXhBsBFZvZQkHOzxqoNEj9MfL+ZRRX5YzXgiKCpbgqDmnF0f192Kky9d/I/lC3KT4LmWvivnU5Vzk'
    b'MXlODufTP8AbCe5olleMfWM517l04+0L5E0A7fmCfCvS6ZLrkBM1LxJ0hItDrS0o5/WJwPAwOqa8JvPpOA535MdLtqQrpCYylJot'
    b'xAYyI3lO1UqNzGYigR04N3+l8Md5xFcacuYniB3UoMHj4Iz9yWenpUdTUMh2gxk/ORTLRiiLjTBh6zmpVw6KI6ALeZfopOGIcwhi'
    b'6JfisMy2lOIguR27ZceAWZa79ovKaU1Z3PZ5Ks46KquMp2K/4gPTCU/L+tghUQgHKSuefj3OaZl9VZEVTTcEVG1/IpBPkovH0Eae'
    b'44kOT8vhDqi9TrKw2P2J3IJvDGVhbKzaHRtzQr6j6OQDvIDDUdGawoGLzMghe9TN1uQJrgEIBdNu3u1QfXkXRphyMMmR+2HQHqI1'
    b'nE8D9nu3om1VHqg+lrCoPgRsZK7SPCTG3NyB1R/iSrNB1b3ZZ+zNPp92V7BZoplghBfkhKvWgBbEGKK8RG8Z0xyEc8wL+FstX61E'
    b'IQMqWYjVdNJAyDE0esWBjjl/KcJbLQO9JjUJZI7EikdqWjXSEgI0U0VCogkMDvbyWZZsgZ9ySL2AmSUueN50JeNB+oBHOuvtctDn'
    b'J8ZJF2y6kzrpzOhqcuhWCI2c3VAyaVcMk4FM3wALlReQldW6k7idE/79kRM9v5qABv7Bzj2/nUBq1ltby9LzQT/qyqTVbDVC4uaF'
    b'/9VZnobTB5Fct9fK1QacKHqqmHk26tPxC/J29vU5KbfXYwFvLHKug29AEWY3ZHgNuqJ8QfC/CeQaYU2FSvcKQrNAj/R2TvSpEbBZ'
    b'Y8wfKKGwnGtJXv/lu0tySF69e/E/M1EOErUX10m2FKeIvPyg9xwu8zxGtVacoLF3kYCUqqacUBAiv91WJKnEDcREiKu/Xr77jlxT'
    b'9PfMNyiGJxmOoS95Qi5RokWB9quSPJ7hKisWymauaJVv05jhBQRenqqWhCaAU44ZlGy5IwWa8cfSjM9g5AvyM7eFsISc4LqkDciu'
    b'I8Iq+ZALPjVjStc7Mptzcd2qH4D1EzBZWZyEmd1TawSgr/OqytdOI/YwCTeg1SrJgGlNNV+PAWGWI9whlDNZGiu4x1d5NSI//kQO'
    b'yV+/e0EOyfvX3/0bwgPLYpFAyq9tBQ1C9kYppQliNl/nhPud0AJxVTKEl5WQ4EPINirsk6wGykjozsMS+8DG8zQPUVhGYUz5FBnK'
    b'mZhWkm2mpAf2YuF+PC/fvikPvOOZvG4E01cHg//JiThZuGjHBGX5ZgvhBPGEvAWVoZgwIHILLzGehvt2lUQr9N5Jb8Md5MSlYG6F'
    b'napWXAGrG+7JcJulyQ0lPyPl/awAcP4RQxLmavzjK+lApPjB9RZSvd5peeqfkfn8/HhK/u39h4NzkgvzzRbcsX/mlxyv0vYz00bg'
    b'cIx1QQbmKEzDAtQsDPe8sXIViEFixPBOMoy3kDmByRssfNJY2TVdwH9+fEWKbVYejEhUhOUKkIYv7MuKm1SvIP8GQvkq2643uwnK'
    b'0GcnJL/+O9DqKgT5nYSiPQGNy1cT8v42gRdzLChK0MiQo16SCfOaZ15KMoU1u89ZTvMv+4Tw8f9ebwcuNL9Noht4dJeVJj9bBwcN'
    b'CvzwiBpgYCAfPydn+L/Ha7ZY6CeSqrAQJzsqY6hZzVXVIlko1InL8Cczg38Q5CLTsqhK2xCg4dbUNnomgHmI34VHCERwxposxrYV'
    b'fmxK0+YuFno4TYzgF719Umrpr1q3dMq9Hn3792dgPnAD4NWstnBZhNk2DYukYuyGSTxRnoIAmsPP4ABrDAobUW6v9T9NHqf/go2R'
    b'uw2YU2y0ykuaOdvOTcnW2OY+G7uM+I8/Rp+a8C8HY2okL755m4dCNRcZ2QGHJH0MvpljjUtvg5+ymyy/zTjhPSbv4KbnlzsCIsMN'
    b'vjuzmxGZXoAoWFYjMrvgFxyX/YBieK8LnX4mCON6J+RYRrkTaAFweQayNa1WeXwxYCn0xSloXL42opJE7VL0TXIpz1ceROm2rGgR'
    b'XOdQi+8+0ul8ei6zoF9vd4RDNrP04zBSr5dlq+01sA+Ij84LIvzbeGikZCRjslg5Mz6e8mqB5yQE/wTUSopBtbQ5VvcsuN7uKLhV'
    b'TuNz9j3brq+ZoCQjiFgbMnx+cYyRGwj1wAfvervjvisSIItl+h+hHIyMIrfmUIYp/f+a+9blto1l3f96ijnUzjJokRQlWnLCRK5S'
    b'HDrxjmS7ZDknKR0XDJEghW0Q4AJASbS3V+2HOE94nuTU190zmAHBi7ySVUs/bAmY6RnMpaenL1/nVhcUPVAUzg3/YxNnJMFEItsx'
    b'PlC8UB80KcAU+axw4dH4IMhCHMgF3FyckNeh6u4fiLamUxF41SSCsjiwFXg0USwFnL87u3z55mygZ5cjoa7ncCzmI9cddTqGSvmQ'
    b'aDw7Ub1ydDUhwlLlBULBrSKThFDYxgt1wNOgRR+tZryCRtGAE0MixnU3tRdfrrw0U0lYIPYeuls9dd1OD6WFsvLKIBm8O8a7Q5l8'
    b'eQphHgBVe2ZN6K/FZ5ImfZgmtxHdFTSp54iQR6jeXchCJc3uM0NCemWWKywHWTQCb/grhZE1m/7hxmfZR5vts/V7z1ZeyH54GCmz'
    b'hSp+fT+iiTYjRcyyVKe5YUGVVrX9oXStd1Q6LbX08boacy/WHJjv/0EdoAO9rYoeoujxVkV7pDc3n/U2iEOzTmjtRWM1pewxYRyj'
    b'Ct1uuXqLruNBgX7xzTiIQ3+UTqMkIAANTw/5MzORqzv1D6d2S96RboQVIvh66egWq4yrb6k/mcZ+EQ5vCMHCDyZZGOLa/M8cVOdn'
    b'6l4ZmsrQZL1FOE1h3AIKTlvnv0GVWTT8qANsz8+Eb3oX0WiCSPKzdALeNlTXcZiMYKiYEvpgbl2HS2PcHQQSVqHobuQKoC0W39fq'
    b'gRZ0O5wLrsVhs0bpo7ViROk2Vya4gOx0SKoBPl0sZmggXvBx1C6yYAbbH6yQAdoI4nY0nWXpbZRM2nKdK9qki21nbPlqY91x5zvq'
    b'f9sJPUzEi8nsMQuzKBWLB6cJCjn1B4J4byJcDqU/fH2H66Fi10NRa8gOuNPsFAcZ8ubBBjskIB/bWjpV02jUHoVD5JlZ0uWIffv8'
    b'zGLSlKDGzL8tnmhmeWrWBOm762xyONFLh0frYSVGpPLWGC0RE32E/K6pYjgIHT7crOkDVEPiIs99OYSw0iMbbG3xQ+cUJVNtbTlj'
    b'mE3YoMvD9w76AiiXCLcGI0a2mNINH0sZSiCzEXCDsHUitFT4NBdzOoLWTXHM6DiI6Ais24nI/MI7cYSgJiKUMopGkc7arzrqNM5T'
    b'7pXJnpfSLFOgyXCewX0iXrBTF/SD4tfV+fdwP13H1f51PqgUW7SFe1ddjuGvN2nyJTRNRgfakZN3Sd3lBcUOTRjUulIQ0z13d9UV'
    b'TXwKS2E/LRgduQX+v2fO2iKcgUHS4u/LRmNe0FKH+q9u56glu4s3HbyGzF+863XG3AcKHLoam7i1aEC0Rdw43KIgCRtHWxTUosa2'
    b'q9OKgKg/tcMEN1YnK+rXHdZESAkhlnpwQUoI0sQ4oyPpVugPccyMonwIJmWdBWGd/7q+YgIeoqz+gSI3DSwLc69ZdJsWHLSEy94n'
    b'YNsicHPmx2mecxIMvwB3Af+G+5Y2RXG0ClVXF/0LNl8zJR6hvAiKea68i8HpT3/sD04vzv7YH/x+OXj10+AnVnBpLDdxvSHo2IgU'
    b'y8NIhAh9PhJCo/6+/3z7+hURIF1yks+n4KU4D5BXTKcku43Cuw9qnxX9o9soTzN122OoDkAWBYiyM0GtkszNTt4VaY5qzdk4uu/r'
    b'lUBkwr/Po9sgBmfXMzkNkVJMe+PGi9I9gG6vlMXMUSdrpVOeqsFvg4s/LFECsG1BTA5HpY/PdZiE4wix2eDR/zXPtQyBUB6IMcaz'
    b'WichA6Au7mJZWGQpO8RJVByGUY47J5uZeAwzWkqKleMcMm+rAXLDdHqNZHjqiRMS53jDxIu+hrU+6KjBcmbJWRh8zCHa73W/wc1+'
    b'70j7GMGz6/wUgPbDYGElEipS6i2Z2Pd6xiUp6oQdcjHD9Vgbrw475BSGNW41ddRtHx9pwnjwQ68LGfLZ0yNTs9dR5yKzqvwuxNV7'
    b'lhYWEeH06C+6TYEG9FXRJyOd2FEke0foaq6VQpxlcxSOTItPOuo3SgBdSQRpqS4kQTS7YRx1R+xXgE4TjV/YLKh5YyMahUEsPIcS'
    b'Ozdka9o7Cy5usGKe0eX+hAjpPav2xWnvLs0AJL0PFUC7FD07loDlhjnmqaLLxL65SrDowiuqRR72GAw+8Orsk1Eyg1iF9KFxGCJt'
    b'LCX7IIHqNgqMAepDDXP+oE08Ibgrdt9Pgxen784u/ReD08t3F4O3f6k4VNOjB0tBlmvTJnmkLOpKQ1/n7P7V4pcbavG1PvwisshO'
    b'YBccuv3Qam2D5bNnl/TTziFfuldxWKh29DrHBnL5r3YXGwZZxvk9sZ1u7VZxaoytQFQhloTzAq6FuEjhusPbcx8aO+3ZJ5Ze261r'
    b'aeduGp9qhYarPqljpn21120b9nnY7bbPTwFZCS4g3E7ewY+U+1Ue7uL7VK7Rg20ku6X67oPONMg/lg4r1qLmsLoSooX80trK86wy'
    b'dvDX4VFznf+KnRj+q/tEIeKHVt55cZZzOrXnerdt0ymZM+sw6vMZ5M5NOi8Io+vqSbelnh7Jlc0KgHjg3Fg19a+Vb5eAih/UE/Zc'
    b'4j+fqadHFpxqt/PEHt2VVHVlCjewlmr9SdqvOUDLxSrH5QkfP52qq+EDB8KqqX+tDIQV63nUrVmUVjTikcz90XZzv7Z9ISvQBHK9'
    b'kWFbIQ4wu/FcKYv0o9DQBwW8Fe9FprhNY9ZWln6fnrfEicjBp0muoIfVTzoqP+lQO9CJdOFVtpkTMmHFM5pObOd+Jve7Nafo5tsa'
    b'gGF8hCjDLjgWpc/XX9t+ZKgZCnpGSklNkU+ISKTpJLwvyM1I7cOvSPxFdMikdXszdE8V91HHM4u7eIb7BTye2E1BPVMQcjXWBq1S'
    b'oPb8v//5v3wzwPEFb9MUOUXQExOmGUFNFMeK4rPvAq2ipE7uHRwefWP5LKVjFvJ/efnmzeAnHuSRhTmqIzx0H/PhPFwWZvmLiJI4'
    b'adF1bqiduACBGJN+jWR4ju9cUnJysmS+ibx+8+b125eXAxUmo77B5ub4jzT9qMjdqBz2UcTi07HO4vzj4MXriwFIRUicfht2JMr0'
    b'ABOvA04JpYTj3OiOTBPOIp6Ntw4Uo/kUrlMRQJKSlO6iYZLPc7UIixbq0fWWb2hYnVEyaWEMiBhpoSUbPUVkwDmYxIgC9UUxjoNA'
    b'i/Rvo3v7cpUTnCahUAbVMNKfTy8H7BtEIEas6v/x9eu3l+YKRkW8KfoGwYbUJVjEVW5C03BCMWtBsiDdZm55Qhx01Bv6Eusb+IoF'
    b'NASEi9mH6gnF4JvKhx0DdMEDQUumLcpyD/gKqGNgWyrVe1y9NxX8J070CbFHKoGfnpCEIwxL8SAozwzKdZqQlxtFO1FIDNTq1gc+'
    b'6VCcJRQKzOBIrnym9nrfKO9J9xttTubYWlPtqIPhQulxVJDLhD+Oo5k/S2ELPFBeb2XV407p14f9OypurMiELhkFDO5BDR0i9ALu'
    b'cX3DocmD4LECU2Wx5QjhJ8KL1c9BEZI4zcugbZ99FLlM1ff4d26sjZigbtfiZZUlSFWgocmiAqqMPjnfRtBHm8EfhQTZdYfb32jK'
    b'kKislqjyErYuea8G78xq2DvsfdNSzwc/k3zQ5J2AOex11XU4DOaiQyJ16B4pQenfY2NvGGYhcMzQvFgfyXBNalOPOTwvRQnaDaJ4'
    b'noVkgVJJeKe7fxNkmBC49OXSUS2+UcibvaaxNR6gqMelnuZKIsit8DTPOoj4MMatXgsI4ajZ4spPUVmsFFyEudosV3tmnal8PkNe'
    b'Mp5yqvctXHaRc/AarLVRHmnH8ImFD1XDwHz8lffnNQf4v+wi7cTRPBiZp1r7q27UwoO2gFCq8iqbClgS2NBGMqt4l00sSkaaP20f'
    b'lFHD0JYD0elsOujbJ4sRZGgHqV8gMvCek2zOfF3CodPCKSE3Jm2MeaCRIkpIF05mHPuiesLSeRPxG+65RrdTp0n6n2V7TW4lLG/t'
    b'hRcwRV266wbXyE5NAU5QS66Wnet6wAaRkrL2adyMk2DPxmFfPbcZ2cHhdM0s9JZn4fCrZ4GsZHrb8RT0eAoswcAdf1Sh/53xP9w4'
    b'/pogDz6SDlpjvz5+ra5xHnoh+nXj3uurATF6YmO9dYMOrTNkHWvQe1896Mbo2NNjDu2LjDnLVTQiTlP0vzPkva2GXIP7YHGX431w'
    b'uOVaL5suB7z38PE+rxFgIBFD7BWgeBEB1KcwSyVYpIzUpQongFDE9nssa4H/723TAZZNn/TV4M1bpZm4vjmo+awvho5up8tmTfnr'
    b'4Ig7QJLZE4FS4+OChrWnx/NBUV+6P0fgwzgJgmvWrBqXGgbDzJAnRNwjPddWJrqH3RJui+M1Vp0uH9iM5x3uHx8eQc5BI2mib6JC'
    b'LE+CWX6TQnB9Fd71aX7SMXWBDzeYJvLcT4IsS+9AYt+CSnmGawmbBXfVDN39zh/2fBTASKMbJJwCagiBXiT0tAm3QHl8SwF1c4/b'
    b'VaadpgSdSBBRNCyoU23qFFsW5fYrgRmVbm7Uk0e+W8N/8veqjFDiu2wlKjhwMIaQNR6bI49XD6ET6Y21CZHS0jgaaQTOD+bxfyuv'
    b'Mi7V15XvJPA1t4T9AaZ2ndOEXuTHffVSy8Lu/coY+bqd3lFLvf6V4wUpgL9IWflnbb/jr3TBRD3+hfmnZ0tXJJBD0fw35TwnJnyk'
    b'FYxr2axdDUyh57LaLThttZvMay26D2S4RhvZ7Twxl9EndDntmb+PKn8fb8NHn7Mxuk8cueZeu/FO6+g2112dH8RQt7nNbFRo1qkJ'
    b'v0aRKQpHZRY644ZDlUdvyPtA6+1oxdM4hPdwfS3NveccZbmvxgBlyxZtKCxnZJjdN3TaeTjFFZDv8KWCbp8CMpkXn57/esHoME2V'
    b'L/KCAVrImRKHLvFU7vx3+D2P8jZ1SG76rNQjSh9IEeED/sO/i2Ap1IbgKFddPrMWpKyj+Gh8C270i0dwoZmh52grDnLm74dP2j2j'
    b'QYwQY2trBlqwbuuwbyjcdMC3k1FFogDpIgPRgbSAWqe7bzSvsJXTRT1eIDaSdSQSlMqNksZgWUlqJXpxXTnbpm8/EJO0GIOcZdch'
    b'4hQI4j2YpC1xnVjSfWhSx1NF/LbnkCpFFJXfBNksXri1elLL7YBEt9omjbKa0Z6W0oZUY4EDIhLhuTiRGSEWRJzeCStwpRE7mrTZ'
    b'p1E1caSjcBwlrPQlEQVMg1fTalnFBLROwmQeJfDJzGdBlofKI55jSzEiWlOjtXp1s5Cn4EQXB91uVzYMlkUYFfDmAIQ/+zFzjyjK'
    b'Dl4RNJWIYAvDGUkVTVHtQwFnImvwoj0N4MpKRLwkLPwoGabTUOCZ2/9x0Dl+8iPB0ZAUY8SXcRxMVBxOoiKaBgW+9YQ3E1H68d2l'
    b'aY/gTKCNNbovw2MoOv0uVHfw1C9SLQ1pQEhMbJhhaku3bZleLeXJ+vCC5nr1qvKM1p0DjWkz6eXlXTdVnTDFVe3toUU9/mUUDrOQ'
    b'vYo0pWGzKnZVF7pntjLWrGBBwVkHWmkpMmquE0WpiGZ+z3va2Uov/eYD9InknnO9sA1P5GpssVSxJM2CPC+NLKQzrDVRsYaSvJOv'
    b'tWMOhy6zQ4947AB3QXwh6tkzlg5StMbpnayHn9IwV69eX2ormAs4wEhiY7qtif1tNs+wMI2D574VCNBxEQRocWM1Nmxep/aYr8yz'
    b'RCs32byE4vM8zB6xN1eUFHNBQoyDyYQ9nsTHg9yUzBn3l+pG6+bjq1ysH4bpUtVnbonq4oK6fJUiVIvsdALoE2KJV9i30Ka5HjqO'
    b'iXRgipxnro1/hk70L7vR/Xvd5gycaDn2zs2uHFTcvlZc6SrIknKN2/r6phcD71x9TNRJNSRqYI+QAVYbWAHuF8K2RMYMhXuevuiA'
    b'YgkAZYHFHz4RsPjeZoTZXXU5z5I2ZCLp2/F0Wb6jojzONnQWMA24mS1Uj9LcxbI81Ve9aSlK6hSFLHjV4msfbNege0OyB+yx9TGP'
    b'nZYe16yaByqkXo4Nu0JIffAK1+F8Ph5Hwwifzo7Ti6ZYrVngh2MeM3mcjOH9mjgEIe5eZHc2cdvNTii2TeafuLE5akEdRScqSgar'
    b'ns8mcPhHEBk/cID4txeHo+kspsgIPlxxv2dpeNm8pOXgUYjE2QxmSfj+vwUJeVR8+Ps8yIowixeDnIXHnBFa4PDfUae/IUosVAWC'
    b'r6JcHUKWiON8fxQs6HZVkZr1Rxjnfd5BEDbZzxfm3C6J3gbaxnj986SjhEk0geSaYTCSIXoV3lU/XlBHcgM70lN5Os+sGP6DWhcB'
    b'zQtPf1Oh/nBJmkDoay25Lehz+bBTlSTtH8+g5tBlHEtBVjvRfHLwHT5Z0+oxrWEwyfwDlxC5sjE4ZnmHIhLdYyZhLPoab8XkJy1v'
    b'm5jmfyClUTpW84QQseAOlRdhMMIz7VNaQjYtX+gaNg4ipKaGLONcVjndKFly4rutPZK4Fhm3WkcArkq95WVYq8wBsalna58H3JSB'
    b'MIsyOpeHhqZCaMCJkod/lbF7iVE8WJzbVc8rKDlmubZUQXc/gdpJ0qQNFkqxsxQclEH0ZorCZL7K2vy1EOVVAaZKR6/mbQhJ2SoV'
    b'KxWP7rawfvOn4f1lf5Yrm991Kh/zt1NdelF3lJ0DhjjVgA+q+w1pJ1uchY8VlWzNE62ke+KWfdl8WNfqIesXWu1JtqtO/oyfnV3N'
    b'up8iDussAEjFQXkI9brNvjpqI2wM0VnZxxDx1ZRjTV/1kCRrV/0U5cMsLKCiuw5jy3HLhFdxbZ9ry+1yX91G9/4n/7g3Uvs7uyqf'
    b'LRynqn16koUFJKE8pUTNiEIPpvoGy+5Vak8ViKAaBvHOLjznUrmAxukEuNa4BmdBMqSY+EBJKmX6KIs92ngkO7scWl9ezs8O98+e'
    b'7p99S/jbd4AtBPb1wsqpjlL8eZ2d3R1EddJTL81GYRaOmv2dXUx0GM44ERy8B9/8oX4QBz04kFqf+4MiXz08LQfpmTrsdImMpqCq'
    b'ZF5fKM+uAPa6TLr3TZPI6GAJ+oExbAGInwnxSG4Hmni7nWdWd8t2kAe40sozdfQNkWDxmvP/rCXRBptfogKeDzLOD3nb8oqq88bD'
    b'Vj2mSRhMEYxd3KUmok+YKs+GXo60FqwfWAqR/QTnRTpWRxyX0VyqY+eZhnuvah/utw/2u/t7B/t7h9DmMVeko/T8rPmnbdydN7+c'
    b'vh0cPPUvBj+/PB/4by9PL8vc8TqDb8PuqyTQdZ5pANad9zs7LqlX784HFy+fqxP1mauZhdvoq7Z4bTT03+JF05D11Ogr8VRsYNob'
    b'faULWIuh0VeHrZ0v1eyrdu9KJvNw4Zw52oHAgwp70rxMmBhzK3PMskAOXwLyNwbCZEddhMEot/nYMDOL6XvtgWsJPvyh5L+qd5cc'
    b'hLnszJNuq8rqTg5a1qo/kcGTpQ0/f6P91WHiGvIxpAV+nRKWPXXqr81/ai+oOjmIYRSbq+qskaCiZCUcoRmtjXJGZVwlKqvGyEwz'
    b'sTnKS7MnncFmmRBa3EJpVs7ualLbOu6t5nwCyF6vlXmNg0hNKa9D3lchhExshhI7y9XGAXmOAuxEahUyAMCMYoJ6TSDASs/0aufl'
    b'Vx5zJ8orpw8WL3ZZkmGT0Bp6xFNCZ5yMx6r6/404GSlNwTEVgl3gAxEFHDoOBVaNW+2BpEOBI99kcq2zy1WmVQmaVxbhdvWF1YLt'
    b'HPE3GNDEq6DEa5J5Yx5lbxfDZVe4MdhbcFfSIBA2szaUqBxHPdyG8lThMp5ZwbvG7zp0mqf/2Q0C09IS3t9cVcgsgJZ9dKwsTiP8'
    b'N/UPTRvnw8rC9qyUdeyjpUSHWmJYRKfurZ3kXNqaebWHYim+m51mmNe/SEj/tiKkDy5fWCm228EdTqRgFMzoQjIMZpDS+Sgbxul8'
    b'5GdhjiNpPyzGfllxXwKK/itHZPtdFhVFCACjHWz7NK4W97XbV2e2UATy0OyYK38gKMeU3aUE89nZxWK8orvUIWAK2m3CmLpnfQKI'
    b'8xIliEZ8l4aLJswLsVjt7CpYeaBoEPhlfbVGRloK/eVNQmfeOIotxcSfJoPxjfHnl8/f6u7yYm0/s7vP5joJ65kCSUq9HTy/fH3h'
    b'Dy5fvFVRssXgNjs7vlS6fI16pVxGlrU0TieLRl81fj/7Vct5UUKp2TnL86pCyIOSDKMgzvnFC/0iTMJMlx7ohzdhEEPQCLKQ3/zm'
    b'vql5IWAgmZbBEKeVCd0/yq4yXLvpxkv9Bnol6/mPS2TzIpjFobx+o1/PKeA80s/flbIvABeYGdCbC/NtSLI9h4mSBgzJraKhrv+8'
    b'tpD18svODmbFPxuc/jS48J+fPv9lgPQnQyjzP39Zfum/Ob38pa9eU46nIL7Ki+y9xshlgdiP02Dkl0uCmZRHci8IG3kXu3r7TZ0C'
    b't8QbBsCybna0lDiJ0+sgVkvdbKn6nmsRcfmjqxLcUgkqMAtIzHkTFDdeY9u+y4EQjRkjPShuOow9aqMAS7Ofv7AKOrPFV4DZnCiQ'
    b'6mBwc49o4OT1YYPwrFwQS92GGA3dOIOa0+7mGYGp8fOXJlw+pNHa+jRsHPVDzepQ+GE4K9SA/nOy29Z1QOivHFleONUl44/RVeqx'
    b'x//BIpfRQsqLzFpHRJYdrcj9BXyG70u4vgYOp/Me3aTFo5Z6dBdk00e8PR4Jz8Vj4c74dRjMooKCMvnvOYMgP2oiWY/cjIq0fF4q'
    b'l91TzTgZA6Qd4BDXYZjA0SfMyKCwCAuzoGWRyPdWV0dDmuKyPI3qZOWWcyhS4Q0Utczi8mxaO5h/7lWzA5Y385odUhHq1ReNpfoS'
    b'QHVtU7u6+9NghiofwwUrrMZZFCYjeBgRNS+cqEc4Bh7RZP5+9msTHm9RjHBVobTmcAeii31qgQPhqCcjQxttyzHXfmZa5psAmUbo'
    b'fOusoA/rQ5oVDn3cMxazsK+iSaL1n+aLTuyiNKr0jS2R25zhlEGjYaeBovKaVKscTSCK0v7RUpPsGX8YzPxSfLG3kLn79BXdtBiy'
    b'jTYW/V2vkvgWEk8wIl+oWZgRrg5s3WQRJtvWjDC+4PCGHcArytoF+IyO+iUt5Clro4/uOSdKHBaKfXhypEIAchBvRaJDWuyn9x0Y'
    b'gcymFN32fcVmYwEwMvQhvul7sgTiHqnfkuITHVblgLk6COYhJ1twJmfOWMBh8SItoERywB8a4Dz01IYEsVRQ8Bu2XghHgm6q89R+'
    b'YfMneuu0oteHzLEnUy7+3V9kUwdF2KoUaP4VV4BvhxXBP5gXqcbOYe/bYCbxMnAI1kI/EoME2fBmH+VN6gxCK+0sgmmsvFEWjMFF'
    b'LWHfLgZL0izNgxjcgPa07tE1IWFPbgB+hpJC4mY+DRL15oKMOuFdEzHpgF0F84Qa9bEibrvcn1LEgeo1gQwLzK4ROztn8zjMhQC+'
    b'dCHQ91pxiEIemc9aYmhvibav3JfQCycTQMsNUzLKBQg4xtW3SNVNmkgC65yN3tLMY0o+iWy8Ava+y1Y6Dj2WvKbzIm2H9zMYYzGa'
    b'mfrAf+V+UHzAvqf0KvSMnDFxjWEHS17zlHuEPhFX85A7ifxIGXdunsgIhzfBbZSS7eXPWWE7/um7y9c+4tveavnVSKeYDCOe2gVF'
    b'qGE5btMaw62cRVuysfs5GfV9vPIgf5ViiSPfnkdJNA1i9ccpcJFRM1OWfwmJJvUNCj87vU2jERgYgsLFJyJMhgtM6GxBq1+UqzLg'
    b'MBjJmUQuknJAhsltlKWiJCEbo6LKEQkjlDgkjsMRHbVT6XQ+TT+GaJiwdjs16YKkB1AkmyQdhG+bXs9zgnh0makj0koviULdkWlx'
    b'UxqQPBiHJOXQgNtCq0iiL4kgJckpW4HbKQ9lOi/Ka02DRrrRV1fvmYZ4NdMMrFo91OuENy0h0Z1gPAQWgHF978i9JLwvOgSnAQxI'
    b'R8QnUEjkpLjrZCJClQPCUhoVwX0cwJyxlrPyIsiKHG6zXmPXTipDnWfjXzlu4IKzdhzehrHOVOQZYdMPEExRbm4AjBkWaUCV2ZBE'
    b'yD8nbl/KDmMtYjjjMPFQpKna9Luu6XybLg0/b0Q2NPoNwgrUreAZS6n8wPnkdvWTP4aLlvJb4GN8M+E6BMWAufMa/UqKHC55G8RG'
    b'duX/G4/+T2M5m87HkNLG6nXivK4dclliVx/DBRbMrUmpsXKK6EyIkSAqKkK48gUZOx9JF+oHQn2MklF/aQVYy5fWN0o1+hYNLEcM'
    b'SksdNK8O3utB+LL0AfLJ7zuAfUpGnk26Mkyr9sLKj0YKG7unS/eEVbUaBmJPN+h/ctfP6vG4qqtMulLr0lvzPcg4s7FjTh0CkeVl'
    b'/uxEHdct88oq5jW85Qp22OcDvvTqo55tfDRLerf6kduEsNLfIB1UOOlWsy48bGlU/snN/qBhQrnbzZt882jWDduDh2s1xdvtNpOc'
    b'gQB3ZxFklew5TrMhjNB430dAYazpLAsmZ/B431OkS+NExCvEEEslTmcnZoiIfAwXliqBavjXFYm2rz57FUG2r8YBbkvlzpNk7f51'
    b'nA4/5jrJD45Kzs+JZstUMn40EuEYPW2pTqdTTgmfaSZRkPmhsfCKbB5igc6CvLCOP65e1SZWJUqjNay+cCzSelk7U7GkVqylDSwS'
    b'rRinDtUPaaOvPn+xrnju6JFAY72VAWn0eR1Yb2xpoNGn3sut0NYYVeXlGqXl8oCcmEQEleW7tOsgKEHVVG3FUmtayySDXuFklQS+'
    b'USm5fT/1fFy5o0SGf+oFa1Kdl7p5I1RpdWlZvnyJRHNQ2shIly+soalyp/B+5o9AFg5bSJjSwU02ylO2lHjVBa1/kvTOrpSkdx5+'
    b'IdibeTFsdrJwFgfD0Cs+wepygpVAhidusMOP9UnNPherqS1LE3oJYvTQl2dC2Nq0q6aslgYzRj107uuvn21I7xOcUM4Ei4r86j3d'
    b'Nq4s+hCvZIonXJgELmtepYNUkJJEunf9UZTjukQpB50XwXQWR+NF9QjMo4nbHteqtsjfVikqnKOmaO0ZyAzaHHlChJ+KU0rtKehd'
    b'LmZ8CrasE7G5pgHth2qNF74TXDQLJ8sVS/F0mS++v8JRQ+cMn9fUSLnKYj0ZkOodrlmR7qmRCls1wnDJn/VPozyYGn0lg2U9qwFT'
    b'aJjzq6xRJ7iRcaam+l2UAGPVqm2e1BVPynJJtcAXnsl122VJ/lipuqLipFgShSO3VYZSZfxACwf0oEblLMA5CxXQjVqi8Niv/HpB'
    b'KWoYuI7XEcHP0oFFj4kK2aopgzb5xAHOcz77HkUI3Ij9nXXku1aowV8ojxwTCausTjaq65D6JRgOwxgnQukEbcQeR8aIxvIxmqki'
    b'AR+EYf5Q+UtGqcqyykyJrLc7Wa2L3HE2Gwt1JWNb3kK03qgEm3o4GhgJPDJPvqNppT+Bc4IQp628pqsOn5G3IlCjDBCC+U8m6Jzl'
    b'G9mK09r6JSpOabxS+fd+6Z20drm6BbULJ/9tVu5vZAkgje9tkEUIS2+3tblhwSrYLL17lJerGcK3tZrNaUSaXS4rntkIUGtDC2Zb'
    b'CiV5q7WSSAEjeX+hbFkaKH75gCWEhfKAFWQLkFR1XQ/4q/NVwNtckn3EDGGZkOpHy+PNXx3EFFMunUbb8lsnC6klz2m2NhuuCHyY'
    b'qfLcgc8hJ0eH45GfZx1odhxxWY64/3Wi19l6DQN8xsB+qj2mLptS5SDKbzobIarrTjn2KTfFNH/ucoppbEsmSPagN3woKjoUVZGC'
    b'2cElQ9yUKfc0fJnC/CaNoegv7mDl5kX8qc34FIiVEIYumWwF5NokwQU4d4prnmU/uQZkmr4d59EnxClQFtIoV+Q7FS9UI0vvCJea'
    b'swvjbV5QeIQmacwg0I72TE8a2KSEtpzdSr7AFLASoxTKcbgUtumTO+pynkBq6+y8Ob28HFy88n88e/38V/+nl28vT189H/iXr88o'
    b'o9UxYijwuW3LEKnz0pCRiyENdLh/lt7lHQoLE2BWau97+kaAXN0EMeJtTcgcWUqjQuXz7JZQh+eFmifAqwZeAeWwRRZGygDjdvXt'
    b'89cXA//N4NXp2eUfkn1LLBtZeufLuelr+ccMOrNMBB/U8ksUYe06P/zk85FrPyvSuDQ2rx5AYa64sxu+egmXDpgZZDHZIkGuPLZX'
    b'VVO98IrT1mN4AeheNVUcccaqKFEfijT+QPE+hClSLrNRNGUQ+iXPDFNEjmrztVWmU2pxEPvGwi6lnYkmPsBLWoJH7n8i7Zimu4pt'
    b'UB1RsNU0Wtvw0vFLHJCyIBsRX5O60m28Jy6PwALuJdyMbTXL9vL+dv3hUTD90YPyJzbJiVs8+fC2tNhUz2hZbq6fqL0TdWCzUIIS'
    b'cOQNAjs4+HbIh6eP05SiEraP/0DCUIJPFwM14MuMA4YsejunPLXLdnRqk49r7YBhiRu2s3CnEifyPTJjTGdpQWltiMRztgaSw53A'
    b'lSCsVxJL6kRMJsuZbMAgZpuHjod5bCI+pLe8TddHy4ihUasdDbCKGSzGjmHBXBgA7u3QYXTU6QhJvO8YlyCYA45bxqucY+G/Mkuc'
    b'/Vipm/ROTRmak4b5XgfasIyEIGWOiMWPcz0MR/L0gIQTogMuOkIwsl3QnEPV2wDHtWhZZjSuBq9ox+zxXyy0ubdet3LlRmxpRfRX'
    b'UKoBblbrQd1KVN71atfMjMJ8KvMEs0/NXK2tg5/R+Kq2HrQCXYd6ZRq3olyt41J1Z4p1uiaEyb5N8AW76uO/VtSMslBWqwMJqUVl'
    b'ZAIROblM5PS2djF7JiRMO2NIyAiVJs41vAmHkDyvcj6wMCyfIbmWEq/fLOVcWAO85hc6p/AUnZEhfG+feuaYs1opxxgjkkcTDOmm'
    b'G5wuSsYAfc22jNfUTa6A9/TbliK6rA5dWWR1SgRdf91daxMWCd6S3HVfnGLO7Fp/7BGBpVANWjurFnlZ3aknq+KwUxHkiVtRyKhx'
    b'1GqP0zhO7+azlrI8tjT67os047PF2Qstk8hySRCrka6ElEZYElmsAAZhmaPymiIO4HI4AxgAITWMxESDwCDeZbtlDZ9SkQpwhwRN'
    b'NDvqnOhAyOaE4us7U14hijTWZ55m3R31Ash1e3L0sjgukj2PT/Vs2LRZZblVzGBmcQB+NAawJ8kF8yT6+zx07kK0mcrDLY59LcXl'
    b'fWRo0P75eWibU7A/ZnB/W9nwErXOfIbh9bzZtaWCJjWmeOM0hQ+UzeyqN2HWLmdUboGikBNFB/Kvy3cg5Fzb4Ejatii5swxEQqTb'
    b'I6y0z8Io0M+++kwj21effJIPvnzRaTCr9xIMTYt+q3gDoAGANcwRX3uCM8tuukGHx9Izh+uxocS4DVkskIV4IH86U1WjCHfEfYv2'
    b'MudZFuCXvRtWcqghGYpdjYCwV6a1rBiodtYer5reEZ563KEC1wsibtd43wKM4XzmY/WcsMW6Y8TTMnLR/omD6fUoUHlfeblqq7wz'
    b'DYPEawJtKu/kxcgbjdLxSZcsWe6DZ6rLk5NTXjLXAoGfinEjziv+KfiBYoE/yiJd++EehhfqhdjuYjFiD59R2R2UW+5Q7cx+wlRh'
    b'2XomD9G2O5rtSCt3cHVi5br7sLMOS5XY4/LUybRl6R0d3CegvUnzoAu3yvv7spUjuI/yk0pCDHdCavhy5cmKs9aORXX4PU0hPdAp'
    b'Yck63jHI/2GmoNEh+hapdF5kcDr+XhWsTyLlxBo9Tcm/wHjYtLCWJ8gX+TIh1Q/FxbUy0XaNTpAsqgIRftBcnA6v7LKwX5rY0/qt'
    b'usRZ1hDZwGr0z+N1o7ViQy/b9UR6rzxj6BvBu1kZJFuawzR8i1+Ct1BwAEt8ojezpHzLsjAcTyxfUzZDPQfcHonA7JOxKSTjqSBt'
    b'cwCU9MXkNS7xZGZD8TdWk+g2ZK9gVyvA3vYfhuNJx3wT07E/7RpYAKj2AWE734sS3/YK3kRBggw+AAK920SniIgEK0hMkGO4o0+s'
    b't90Jxo1erI9VBqhj3zSvUd3g+g/4m2EQA3on/GgwExExibzaepM9Vi/mJFpRSnej44iSIpywcY8DvKpjfR0C+NiSxBiHQFI9wDV5'
    b'nMYR8DemszQxKYQtNcBwPFn2iNzVgWYY7hnEdDZ1ojCybJEq2UvH47Zc8WAhMom/gWYgYWq2c9ESKgownty3K19YOCnLlRgbxU2/'
    b'WwOeQilJTYEv9aZB3XMTe2YvVwFTFPBXGZkTNQmLoCgybzietFRjm2XcaNGA2+efdmLMyS8+GYaeNMCy4rLpURwltm1bPkzANATT'
    b'g9Sx0s6qL/6nWlhrg/0qiyvbDv5SPC8L0OvwO2AF3M/iNIfJg4wd0U2ajugMluj4l8k4zELcNORqoUbQ91K+1/3wPirU7z//SMkZ'
    b'pukoROh9FhD0tRU6RI/8kFtKE0s3CSaCiPSbUMASaf8jzqKgCFtoXnd2gUA4mg/ZasUkEaw40iRvQyPkjK47s0XHQnvqOVhPHJfI'
    b'MUdlfzh5rUFvmgb3uKS+8eh5E/ra9sHhfvt4v91TUwQFZdGnNMmrVO6BO2wgoEoq91FBRABgu7/X2987XkMFiO8WjhR1AWj7GGnA'
    b'wcu97nv1jASh+aKlfsBv1Ap9N2Gw0lRYQESAArufcBYNvv/oAJXXF0b9HCWzeUHVgJxGWdlbdEmGCVLLZLmTZ51MbDhMPoL3DdMY'
    b'CoGoCOFrCnMgm9PylroL4o9tnUqWFgTjQceMfA/jWo70BMi+QLJwFl1TItfOnw+TNfj9zdnrty9fv1rGyKpdFAYGoWaul9+ZGRQk'
    b'rbK189c/Dc6W8QAYOgJsqi+7JzNTQhfW9jO69EAgthDmokSX8rFzQhOA2rTbfDE4vXx3MfDPT9+Yr/Q49yHAh5Z+rvS79zUvqz/g'
    b'hS2LZG8Nyd7XkTxeQ/L460hy0sd6kni3BU2bJHJm97qjWpK3KSJJKSc2F2kERXbwxJ8Ni2ozhBJp0/xuM83vNtPUyeG9xjS490ej'
    b'OrJX/C4L7gCqqKla5W2y9qdnuX+b+wxk5BK9wrvrMBneAJ9qw+TXkzxeT/L4ASQj/+BJ/TLK8ujgyVarSB3ZNCk5NPV0GvhHgNoq'
    b'aS6/ayCxjH90eOffRJMba6ZWkmT4rnqS/K5BGF9+Hqez0N6vlaWJ9PH5PJtALHO+3H7n97r+wbdEVafx9OX9JxA+sGiO0jgOMrz2'
    b'g9uJf9gd+XE6AfWrVe/qhtfZlIiqJ3BaTarsZpxO/OnHYhjM6Jvdki5hJvnehUwxbJnPxBrIlLPg06KNwkaS+c+3r19x/iiTWymd'
    b'Fzgb9+skjn0mvV+JmCcG/1ks76xHFZpfWDQWvEAG2aS03RqSmW2dZNxlKOB8PhyGeT6eI+EJsLCl71q6XnHIVOXL+mIrI0m1wBDk'
    b'+HVjZKiLtkKD4o+izIQEbzGGLqqLIbEZ2kWS0OsTjoaHT/CDw2mKpcN/Hdt/9PCHVR6HelD4kNOoEP5GjDY94dJLT48NjffLQbHc'
    b'ORKcJ6Rzln5a0bS4o5iR2lfjxudiUnxhiBtbSUXG35pxqFUdLrmDyMJTJ5jIzu8///i8BNNs1pUkTBzeM3RvmlU81KH7KSak5Zca'
    b'W4YfOH3leAMb56ZufWozSTpfpTHynesA1EUiGE2DIovu6/1FjJoIANSjIMuChcQjNBqN0zwPp1Ak4mpycNQW8UuLZUyXZlQENgL2'
    b'FQ5gzHmevBXXpFJ4K2W1Fom+7AVCW90UYtsX4ugTsaF/D+yymNIqkMsG3caYTke9nYWA7moPceVz+WTfYMkYZmruBZTnjB9JW6XZ'
    b'MU4nBzOP34oC5OE+FsZig8tBn4LQ7BHHli0N2hvHCwNRL92WDeeWCtBYCp2Yc93cEOTKVpZMRsN1vgvU1JKdZzS+Gm6jdKVz1t7g'
    b'pfct+W9aA0EBFpWTj2NA5WBc18vpsK6LumZNTx2gcrff+Npk1pFlYcUm2d2vWEdcbFeeRANVOV6ZclMvGB0mkmvnDb1v5INmCwdy'
    b'3+EPyUyGBOqe4UdcofJmNfOHYRml+mNFBpDWFtrlbYGIGYmY7/mmC3LZB5JAVEDncc0JfeE4zYwFQabswXVshJVSmVLqXtLEVqfk'
    b'87yg53KCS3O58vYOjrrf4Ba/9223+w2W0fE0bRH3QLz1f/S63fNWWV8FHMByuYfEPc2OUbGcn7UNHpMGHl5GYuSczOJjICoK+IAw'
    b'T2V1BWsdaHQ0/oYcGOxDAAcgWrF/DrAxMYGUMvOtVA7YkMfDNCb3JOjpNBtkvqc9V8ll0Y9yPyRD1MjjjE0HT8ul1jDc7AQR8ctC'
    b'jQAdyxCdrBRll2SlfBWp30Fl0yFp6P1eDQT4fUUIgFBnacqSwbYTvZjtkzzl1P1aMey93Rtsn7XHDRPYVMqS3ZyvdJzqpEB1ClbG'
    b'A1o91PyN65JI1ZllIQRIKhB4vzev+khBURshuELIWhK07M+wxvuf+wozgP+Cj9BL055ca1+u0NtRiOysMw3uo+l82slCaJE9i4YV'
    b'MWxWwwqypcZvBVVDoUziUaMTdK26a3reXt0+VXcO6vZBTcKxFcmuiptwGrJrtWYB+UM8qrNgpm2CoJR3gqIIhjf+LMx81q9LE4ax'
    b'kyMFqfDJ2MeMXeMxkX+x1aUyvsOXPEzI6FFfADp2OW9YlSAiTss+kZo4e3Bmknobx8Ty0SQmOIwdIh/5TslfR3BK86TEYyJGT0Es'
    b'MbDt5MoOglFSpO7QfCbOzX8YuVqGJ5hMMuQf1mEfm4bxy59z5HGqEp+TWvi1xswGNywWCj0NALjV+Het5bIxkJo5/WIc2nUMQDnV'
    b'+WJ3QiPbr+sFGYP8LMo/+jmiR4roFqrPsgFK+75lrWlwv6oGJ5ueZ0GskxxtaGK5whrqogbCMPmcqtoif3Bo232lBtSv9cV7xzXF'
    b'85s0KyT5OIKgnN5vUVz3vWtPE92tIXjLUtTz5FEYxlYcw5KynEtc/TJc6TsMIU389qjt1Vcyeq0FNaG7s7JA+cfSBcPyHN/mS6pr'
    b'+V/+Ke4lr3xVc8WrfGpVrKO6NfJtg/lS6dW/3PXRVWM9M6cD0IYpWF0DS7JaWisy6xalCLCOsELKW5sla92m61m1ife6vhfr+bj+'
    b'sVm/8+Lyl8H5wKf7hn/+7uzy5Zuzl4OLsswm4JV/hzHmsZSQGf7LvY/ws3+rTu+qi3mi9HSRCxdhbTqu7nAcF52bV3W7Fyd2Uu2R'
    b'x7T+4DrX5ZrNAbPK8GaeUCSQXDBokUJ/BvfdW+A6UQmmoP17q/SRdjMrxLG34mA+gdfOqhXqEfGWzE6zZg8wOMOG7eCSaaHRJfWw'
    b'fKm+G2jqZTmO5ZlhnJJhUHhlnZagViKXeHgvnynKYj2ADJuzs+xQvGEARssfzx3Z+M2jmu8FdmwOhbCdc4m9VllFW8n6tKOnW5QO'
    b'3qZNAa+k1ZvAjWe1DpaVfqzQ28t5Ye8e6/Gy2/r6Q6R63ajdgaS6//+zkLeCNIkEAA=='
)
HISTORICAL_FEATURES_COMPRESSED_SIZE = 66124
HISTORICAL_FEATURES_COMPRESSED_SHA256 = '6cd289d28618ab4ac8e5363e1891637021a2bd37e91030a62f18622ced14b53c'


def historical_feature_fixture_bytes(name, source_commit):
    try:
        blob, expected_size, expected_sha = HISTORICAL_FEATURE_INPUTS[name]
    except KeyError:
        raise ValueError('historical_feature_fixture_name') from None
    if not 0 < expected_size <= 1024 * 1024:
        raise ValueError('historical_feature_fixture_size')
    # Both reviewed originals may be absent from a depth-one checkout. Neither
    # current HEAD source nor an on-demand network fetch can replace them.
    git_environment = {**os.environ, 'GIT_NO_LAZY_FETCH': '1'}
    try:
        size_text = subprocess.check_output(['git', 'cat-file', '-s', blob], cwd=ROOT,
                                            stderr=subprocess.PIPE, env=git_environment).strip()
    except subprocess.CalledProcessError:
        if name == 'r1000_pipeline.py':
            archive = HISTORICAL_FEATURE_PIPELINE_GZIP
            compressed_size = HISTORICAL_FEATURE_PIPELINE_COMPRESSED_SIZE
            compressed_sha = HISTORICAL_FEATURE_PIPELINE_COMPRESSED_SHA256
        else:
            archive = HISTORICAL_FEATURES_GZIP
            compressed_size = HISTORICAL_FEATURES_COMPRESSED_SIZE
            compressed_sha = HISTORICAL_FEATURES_COMPRESSED_SHA256
        if not isinstance(archive, bytes) or not 0 < len(archive) <= 512 * 1024:
            raise ValueError('historical_feature_fixture_size')
        compressed = base64.b64decode(archive, validate=True)
        if (not 0 < len(compressed) <= 384 * 1024 or
                len(compressed) != compressed_size or
                hashlib.sha256(compressed).hexdigest() != compressed_sha):
            raise ValueError('historical_feature_fixture_hash:' + name)
        with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as handle:
            raw = handle.read(expected_size + 1)
    else:
        if not size_text.isdigit() or len(size_text) > 8 or int(size_text) != expected_size:
            raise ValueError('historical_feature_fixture_size')
        process = subprocess.Popen(['git', 'cat-file', 'blob', blob], cwd=ROOT,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=git_environment)
        try:
            raw = process.stdout.read(expected_size + 1)
            if process.wait(timeout=15) != 0:
                raise ValueError('historical_feature_fixture_hash:' + name)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=15)
            process.stdout.close()
    if len(raw) != expected_size or hashlib.sha256(raw).hexdigest() != expected_sha:
        raise ValueError('historical_feature_fixture_hash:' + name)
    return raw


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                               cwd=ROOT, text=True).strip()
        paths = {'AGENTS.md', 'docs/RUN287_GITHUB_AGENT_OPERATING_STANDARD.md',
                 'docs/AGENT_SHARED_LESSONS_LEDGER.md', 'docs/MANUAL_FOUNDATION_V1.md'}
        for key in manual.PLAYBOOK_IDS:
            paths.update(manual.required_dependencies(key))
        for row in manual.load_catalog()['entries']:
            paths.update(row['dependency_hashes'])
        for name in paths:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            # Sparse CI omits some tracked proof inputs. Reconstruct only this
            # temporary fixture from one immutable checked-out Git snapshot.
            target.write_bytes(fixture_dependency_bytes(name, source_commit))
        catalog = manual.load_catalog(self.root)
        for row in catalog['entries']:
            if row['entry_id'] == 'group_577' and row['classification'] == 'REUSE_NOW':
                # This positive exercises the historical reviewed catalog. Do
                # not mix current financial code into its temporary snapshot.
                reviewed = HISTORICAL_FEATURE_INPUTS
                for name, (blob, size, expected_sha) in reviewed.items():
                    if name not in row['dependency_hashes']:
                        raise ValueError('unknown_historical_feature_pin:' + name)
                    raw = historical_feature_fixture_bytes(name, source_commit)
                    if len(raw) != size or hashlib.sha256(raw).hexdigest() != expected_sha:
                        raise ValueError('historical_feature_fixture_hash:' + name)
                    (self.root / name).write_bytes(raw)
                    # Explicit historical positive, not the current catalog's
                    # newly reviewed source. Rebind only these fixed original
                    # operands inside this temporary test snapshot.
                    row['dependency_hashes'][name] = expected_sha
        self.write(manual.CATALOG, catalog)
        for row in catalog['entries']:
            if row['entry_id'] in {'group_423_574', 'group_591'} and row['classification'] == 'REUSE_NOW':
                for name, expected_sha in row['dependency_hashes'].items():
                    target = self.root / name
                    target.write_bytes(historical_catalog_fixture_bytes(target.read_bytes(), expected_sha))

        # Frozen577 import positives retain their reviewed Source bytes. Current
        # Source changes must continue to fail production catalog lookup.
        frozen_sec = historical_sec_fixture_bytes()
        for name, raw in frozen_sec.items():
            if any(row['classification'] == 'REUSE_NOW' and
                   row['dependency_hashes'].get(name) == HISTORICAL_SEC_FILES[name]
                   for row in catalog['entries']):
                (self.root / name).write_bytes(raw)

        # Restore reviewed originals only inside temporary historical positives.
        # Production catalog pins and changed-current-source refusal stay intact.
        for name, raw in historical_a3_fixture_bytes().items():
            if any(row['dependency_hashes'].get(name) == HISTORICAL_A3_FILES[name]
                   for row in catalog['entries']):
                (self.root / name).write_bytes(raw)

    def write(self, name, value):
        (self.root / name).write_text(json.dumps(value, indent=2) + '\n')

    def use_historical_reader_catalog(self):
        """Keep reviewed Reader/Lake inputs in the historical test root only."""
        historical = {name: historical_reader_fixture_bytes(name) for name in HISTORICAL_READER_INPUTS}
        historical['tools/long_history_lake.py'] = historical_lake_fixture_bytes()
        catalog = manual.load_catalog(self.root)
        for row in catalog['entries']:
            if row['entry_id'] in {'group_423_574', 'group_591'}:
                for name in row['dependency_hashes'].keys() & historical.keys():
                    row['dependency_hashes'][name] = hashlib.sha256(historical[name]).hexdigest()
        for name, raw in historical.items():
            (self.root / name).write_bytes(raw)
        self.write(manual.CATALOG, catalog)

    def reconciled_main_proof_paths(self):
        programs = {
            '.github/workflows/alpaca_sip_private_backfill_v1.yml',
            'tests/alpaca_sip_private_backfill_v1_smoke.py',
            'tests/daily_crisis_report_clock_smoke.py',
            'tests/theme_classification_smoke.py',
            'tools/alpaca_sip_private_backfill_v1.py',
            'tools/daily_crisis_report_clock.py',
        }
        folder = 'docs/theme_memory_fix_evidence_20261015/'
        members = {f'{day}_{kind}.csv' for day in ('20260510', '20260512')
                   for kind in ('membership_changes', 'score_comparison', 'themes_after', 'themes_before')}
        members.update({'performance_correction.json', 'recalculation.json'})
        inputs = {folder + name for name in members} | {
            folder + 'manifest.json', 'docs/DAILY_CRISIS_REPORT_CLOCK_HISTORY_V1.md',
            'tests/fixtures/theme_memory_20260510.csv',
            'tests/fixtures/theme_memory_members_20260510.csv',
        }
        return programs, inputs, members

    def test_reconciled_source_theme_b1_main_paths_are_fixed_and_present(self):
        programs, inputs, _ = self.reconciled_main_proof_paths()
        self.assertEqual((len(programs), len(inputs)), (6, 14))
        self.assertTrue(programs.issubset(manual.A6_FIXED_PROOF_PROGRAMS))
        self.assertTrue(inputs.issubset(manual.A6_FIXED_PROOF_INPUTS))
        self.assertEqual(len(manual.A6_FIXED_PROOF_PROGRAMS), len(set(manual.A6_FIXED_PROOF_PROGRAMS)))
        self.assertEqual(len(manual.A6_FIXED_PROOF_INPUTS), len(set(manual.A6_FIXED_PROOF_INPUTS)))
        required = set(manual.required_dependencies('A6_INDEPENDENT_QA', self.root))
        self.assertTrue((programs | inputs).issubset(required))
        for path in programs | inputs:
            self.assertTrue((self.root / path).is_file(), path)

    def test_reconciled_theme_manifest_members_match_actual_bytes(self):
        _, _, members = self.reconciled_main_proof_paths()
        folder = self.root / 'docs/theme_memory_fix_evidence_20261015'
        manifest = json.loads((folder / 'manifest.json').read_bytes())
        self.assertEqual({row['path'] for row in manifest['files']}, members)
        self.assertEqual(len(manifest['files']), 10)
        for row in manifest['files']:
            raw = (folder / row['path']).read_bytes()
            # The archived manifest binds Git-LF bytes, not a Native CRLF
            # checkout. Verify that context explicitly without changing pins.
            name = 'docs/theme_memory_fix_evidence_20261015/' + row['path']
            committed = subprocess.check_output(['git', 'show', 'HEAD:' + name], cwd=ROOT)
            self.assertEqual(raw.replace(b'\r\n', b'\n'), committed)
            self.assertEqual(len(committed), row['size_bytes'])
            self.assertEqual(hashlib.sha256(committed).hexdigest(), row['sha256'])

    def test_reconciled_main_proof_inputs_refuse_tamper_omission_and_loss(self):
        programs, inputs, _ = self.reconciled_main_proof_paths()
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
        for name in sorted(programs | inputs):
            with self.subTest(path=name):
                target = self.root / name
                original = target.read_bytes()
                renamed = target.with_name(target.name + '.renamed')
                omitted, omitted_scope = copy.deepcopy(packet), copy.deepcopy(scope)
                omitted['dependencies'].pop(name)
                omitted_scope['dependencies'].pop(name)
                self.bind(omitted)
                try:
                    for changed in (original + b'\n# changed proof bytes\n', b''):
                        target.write_bytes(changed)
                        self.rejected(packet, scope, 'dependency_bytes_changed')
                    target.write_bytes(original)
                    self.rejected(omitted, omitted_scope, 'missing_dependency')
                    target.unlink()
                    self.assertIn(name, manual.required_dependencies('A6_INDEPENDENT_QA', self.root))
                    self.rejected(omitted, omitted_scope, 'missing_dependency')
                    with self.assertRaises((OSError, manual.ContractError)):
                        self.validate(packet, scope)
                    target.write_bytes(original)
                    target.rename(renamed)
                    self.rejected(omitted, omitted_scope, 'missing_dependency')
                    if name == '.github/workflows/alpaca_sip_private_backfill_v1.yml':
                        result = self.cli_fixture(omitted, omitted_scope)
                        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                        self.assertEqual(json.loads(result.stdout)['reason'], 'missing_dependency')
                        self.assertEqual(result.stderr, '')
                finally:
                    if renamed.exists():
                        renamed.unlink()
                    target.write_bytes(original)
        self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')

    def test_a6_private_capture_local_tool_imports_are_pinned(self):
        # Derive the consumer's local imports independently of the fixed inventory.
        consumed = {'tools/twelve_private_capture.py', 'tools/twelve_private_cohort.py'}
        for name in tuple(consumed):
            tree = ast.parse(fixture_dependency_bytes(name, 'HEAD'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == 'tools':
                    consumed.update('tools/' + alias.name + '.py' for alias in node.names)
                elif (isinstance(node, ast.ImportFrom) and node.module and
                      node.module.startswith('tools.')):
                    consumed.add(node.module.replace('.', '/') + '.py')
                elif isinstance(node, ast.Import):
                    consumed.update(alias.name.replace('.', '/') + '.py'
                                    for alias in node.names if alias.name.startswith('tools.'))
        missing = consumed - set(manual.required_dependencies('A6_INDEPENDENT_QA', self.root))
        self.assertEqual(missing, set())

    def test_a6_cohort_helper_proof_and_stale_rebound_absence_controls(self):
        name = 'tools/twelve_private_cohort.py'
        target = self.root / name
        original = fixture_dependency_bytes(name, 'HEAD')
        target.write_bytes(original)
        controls = {path: (self.root / path).read_bytes()
                    for path in (manual.MANIFEST, manual.CATALOG)}
        prefix = [sys.executable, '-B'] + (['-O'] if sys.flags.optimize else [])
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1',
                   PYTHONOPTIMIZE=str(sys.flags.optimize))
        env['PYTHONPATH'] = str(self.root) + os.pathsep + env.get('PYTHONPATH', '')
        # Execute only the real registered offline leaf; its run/provider call is mocked.
        runner = ('import importlib.util,sys,unittest; '
                  's=importlib.util.spec_from_file_location("actual_capture_proof",sys.argv[1]); '
                  'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
                  'suite=unittest.TestSuite([m.PrivateCaptureTests('
                  '"test_known_provider_or_configuration_failure_is_safe_at_cli_boundary")]); '
                  'r=unittest.TextTestRunner().run(suite); sys.exit(not r.wasSuccessful())')
        def proof():
            return subprocess.run(prefix + ['-c', runner,
                str(self.root / 'tests/twelve_private_capture_smoke.py')], env=env,
                capture_output=True, text=True, timeout=30)
        try:
            canonical = proof()
            self.assertEqual(canonical.returncode, 0, canonical.stdout + canonical.stderr)
            target.write_bytes(original + b'\nraise RuntimeError("synthetic-unreviewed-proof-input")\n')
            changed = proof()
            self.assertEqual(changed.returncode, 1, changed.stdout + changed.stderr)
            self.assertIn('UNEXPECTED_FAILURE', changed.stderr)
            target.write_bytes(original)
            restored = proof()
            self.assertEqual(restored.returncode, 0, restored.stdout + restored.stderr)
            for attack in ('stale', 'rebound-omission', 'rebound-deletion', 'retained-deletion'):
                with self.subTest(attack=attack):
                    try:
                        packet, scope = self.packet('A6_INDEPENDENT_QA')
                        good = self.cli_fixture(packet, scope)
                        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
                        target.write_bytes(original + b'\nraise RuntimeError("unreviewed")\n')
                        reason = 'dependency_bytes_changed'
                        if attack.startswith('rebound-'):
                            packet['dependencies'].pop(name, None)
                            scope['dependencies'].pop(name, None)
                            if attack == 'rebound-deletion':
                                target.unlink()
                            self.rebind_schema_fixture(packet, scope)
                            reason = 'missing_dependency'
                        if attack == 'retained-deletion':
                            target.unlink()
                            with self.assertRaises((OSError, manual.ContractError)):
                                self.validate(packet, scope)
                        else:
                            self.rejected(packet, scope, reason)
                        refused = self.cli_fixture(packet, scope)
                        self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
                        self.assertEqual(json.loads(refused.stdout)['status'], 'BLOCKED_INPUT')
                        if attack != 'retained-deletion':
                            self.assertIn(reason, json.loads(refused.stdout)['reason'])
                        self.assertEqual(refused.stderr, '')
                    finally:
                        target.write_bytes(original)
                        for path, raw in controls.items():
                            (self.root / path).write_bytes(raw)
            packet, scope = self.packet('A6_INDEPENDENT_QA')
            result = self.validate(packet, scope)
            self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
            self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
            for field in ('worker_invoked', 'completed_task', 'economic_authority'):
                self.assertFalse(result[field])
        finally:
            target.write_bytes(original)
            for path, raw in controls.items():
                (self.root / path).write_bytes(raw)


    def test_a6_promotion_evidence_refuses_stale_and_rebound_missing_pin(self):
        name = 'data_static/run287_promotion_evidence_current.json'
        self.assertIn(name, manual.required_dependencies('A6_INDEPENDENT_QA', self.root))
        target = self.root / name
        original = target.read_bytes()
        controls = {path: (self.root / path).read_bytes()
                    for path in (manual.MANIFEST, manual.CATALOG)}
        try:
            for attack in ('stale', 'rebound-omission', 'rebound-deletion'):
                with self.subTest(attack=attack):
                    target.write_bytes(original)
                    for path, raw in controls.items():
                        (self.root / path).write_bytes(raw)
                    packet, scope = self.packet('A6_INDEPENDENT_QA')
                    target.write_bytes(original + b'\n')
                    reason = 'dependency_bytes_changed:' + name
                    if attack.startswith('rebound-'):
                        packet['dependencies'].pop(name)
                        scope['dependencies'].pop(name)
                        if attack == 'rebound-deletion':
                            target.unlink()
                        self.rebind_schema_fixture(packet, scope)
                        reason = 'missing_dependency'
                    self.rejected(packet, scope, reason)
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertEqual(json.loads(cli.stdout)['reason'], reason)
                    self.assertEqual(cli.stderr, '')
        finally:
            target.write_bytes(original)
            for path, raw in controls.items():
                (self.root / path).write_bytes(raw)
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        accepted = self.validate(packet, scope)
        cli = self.cli_fixture(packet, scope)
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertEqual(accepted['status'], 'VALIDATED_PREPARE_ONLY')
        self.assertEqual(set(accepted['proof_results'].values()), {'NOT_RUN'})
        for field in ('worker_invoked', 'completed_task', 'economic_authority'):
            self.assertFalse(accepted[field])

    def test_declared_pr_group_matches_both_source_mapping_key_sets(self):
        original = (self.root / manual.CATALOG).read_bytes()
        try:
            for key, selected in (('L0_RESUME_HANDOFF', False),
                                  ('L0_RESUME_HANDOFF', True),
                                  ('A1_SOURCE_ADMISSION_REFRESH', False),
                                  ('A6_INDEPENDENT_QA', False)):
                with self.subTest(playbook=key, selected=selected):
                    (self.root / manual.CATALOG).write_bytes(original)
                    packet, scope = self.packet(key)
                    catalog = json.loads(original)
                    row = next(row for row in catalog['entries']
                               if row['entry_id'] == 'group_423_574')
                    self.assertEqual(row['pr_or_group'], '#423/#574')
                    row['source_heads'].pop('#574')
                    row['source_metadata'].pop('#574')
                    self.write(manual.CATALOG, catalog)
                    if selected:
                        packet['reuse_entries'] = ['group_423_574']
                    self.rebind_all(packet, scope)
                    with self.assertRaisesRegex(manual.ContractError, 'catalog_pr_head_identity'):
                        manual.lookup_reuse('group_423_574', root=self.root)
                    self.rejected(packet, scope, 'catalog_pr_head_identity')
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertEqual(json.loads(cli.stdout)['reason'], 'catalog_pr_head_identity')
                    self.assertEqual(cli.stderr, '')
        finally:
            (self.root / manual.CATALOG).write_bytes(original)
        catalog = manual.load_catalog(self.root)
        self.assertTrue(manual.lookup_reuse('group_423_574', root=self.root)['allowed'])
        issues = [row for row in catalog['entries'] if row['source_kind'] == 'ISSUE']
        self.assertTrue(issues)
        self.assertTrue(all(not row['source_heads'] for row in issues))
        for key in manual.PLAYBOOK_IDS:
            packet, scope = self.packet(key)
            accepted = self.validate(packet, scope)
            self.assertEqual(accepted['status'], 'VALIDATED_PREPARE_ONLY')
            self.assertEqual(set(accepted['proof_results'].values()), {'NOT_RUN'})
            self.assertFalse(accepted['economic_authority'])

    def a6_bound_input_controls(self, name):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(fixture_dependency_bytes(name, 'HEAD'))
        original = target.read_bytes()
        controls = {path: (self.root / path).read_bytes()
                    for path in (manual.MANIFEST, manual.CATALOG)}
        try:
            for attack in ('stale', 'rebound-omission', 'rebound-deletion'):
                with self.subTest(path=name, attack=attack):
                    target.write_bytes(original)
                    for path, raw in controls.items():
                        (self.root / path).write_bytes(raw)
                    packet, scope = self.packet('A6_INDEPENDENT_QA')
                    target.write_bytes(original + b'\n')
                    reason = 'dependency_bytes_changed:' + name
                    if attack.startswith('rebound-'):
                        packet['dependencies'].pop(name, None)
                        scope['dependencies'].pop(name, None)
                        self.rebind_schema_fixture(packet, scope)
                        if attack == 'rebound-deletion':
                            target.unlink()
                        reason = 'missing_dependency'
                    self.rejected(packet, scope, reason)
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertEqual(json.loads(cli.stdout)['reason'], reason)
                    self.assertEqual(cli.stderr, '')
        finally:
            target.write_bytes(original)
            for path, raw in controls.items():
                (self.root / path).write_bytes(raw)
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        accepted = self.validate(packet, scope)
        cli = self.cli_fixture(packet, scope)
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertEqual(accepted['status'], 'VALIDATED_PREPARE_ONLY')
        self.assertEqual(set(accepted['proof_results'].values()), {'NOT_RUN'})
        for field in ('worker_invoked', 'completed_task', 'economic_authority'):
            self.assertFalse(accepted[field])

    def test_a6_default_lifecycle_csv_is_immutable_proof_input(self):
        name = 'data_static/run287_exact_packet/security_lifecycle_events.csv'
        for proof in ('tests/daily_simulated_fill_ledger_smoke.py',
                      'tests/run287_paper_ledger_transaction_smoke.py'):
            self.assertIn(proof, {path for path, _ in registered_validation.DEFAULT_TESTS})
            self.assertIn('"security_lifecycle_events.csv"',
                          fixture_dependency_bytes(proof, 'HEAD').decode())
        self.a6_bound_input_controls(name)

    def test_a6_default_candidate_metadata_is_immutable_proof_input(self):
        self.assertIn('tests/post_disclosure_alpha_candidates_smoke.py',
                      {path for path, _ in registered_validation.DEFAULT_TESTS})
        witness = fixture_dependency_bytes('tools/run_post_disclosure_alpha_candidates.py', 'HEAD').decode()
        self.assertIn('DEFAULT_METADATA = "cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv"', witness)
        self.a6_bound_input_controls('cloud_results/full_rebuild/latest_global_alpha_universe/scored_latest.csv')

    def test_a6_catalog_only_reuse_dependencies_are_immutable_proof_inputs(self):
        names = ('docs/CANDIDATE_REASSESSMENT_BRIDGE_V1.md',
                 'docs/CANDIDATE_REGISTRY_V1_REFERENCE_INDEX.md',
                 'docs/EARNINGS_CONSENSUS_SOURCE_V2.md',
                 'docs/RESEARCH_DATA_ACCESS.md',
                 'docs/SHARED_RESEARCH_READER_V1.md',
                 'tests/g6_h1_regime_data_native_smoke.py')
        catalog = manual.load_catalog(self.root)
        consumed = {path for row in catalog['entries'] if row['classification'] == 'REUSE_NOW'
                    for path in row['dependency_hashes']}
        for name in names:
            with self.subTest(name=name):
                self.assertIn(name, consumed)
                self.a6_bound_input_controls(name)
        self.assertTrue(consumed.issubset(manual.required_dependencies('A6_INDEPENDENT_QA', self.root)))

    def test_a6_broker_audit_refuses_stale_and_rebound_missing_pin(self):
        name = 'research/broker_accounting_audit.json'
        self.assertIn('tests/auto_policy_challenger_smoke.py',
                      {path for path, _ in registered_validation.DEFAULT_TESTS})
        witness = fixture_dependency_bytes('tests/auto_policy_challenger_smoke.py', 'HEAD').decode()
        self.assertIn('def test_repository_audit_matches_schema_and_documents_open_bugs()', witness)
        self.assertIn('audit_path = REPO_ROOT / DEFAULT_BROKER_ACCOUNTING_AUDIT', witness)
        self.assertIn(name, manual.required_dependencies('A6_INDEPENDENT_QA', self.root))
        target = self.root / name
        original = target.read_bytes()
        controls = {path: (self.root / path).read_bytes()
                    for path in (manual.MANIFEST, manual.CATALOG)}
        try:
            for attack in ('stale', 'rebound-omission', 'rebound-deletion'):
                with self.subTest(attack=attack):
                    target.write_bytes(original)
                    for path, raw in controls.items():
                        (self.root / path).write_bytes(raw)
                    packet, scope = self.packet('A6_INDEPENDENT_QA')
                    target.write_bytes(original + b'\n')
                    reason = 'dependency_bytes_changed:' + name
                    if attack.startswith('rebound-'):
                        packet['dependencies'].pop(name)
                        scope['dependencies'].pop(name)
                        if attack == 'rebound-deletion':
                            target.unlink()
                        self.rebind_schema_fixture(packet, scope)
                        reason = 'missing_dependency'
                    self.rejected(packet, scope, reason)
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertEqual(json.loads(cli.stdout)['reason'], reason)
                    self.assertEqual(cli.stderr, '')
        finally:
            target.write_bytes(original)
            for path, raw in controls.items():
                (self.root / path).write_bytes(raw)

    def test_catalog_top_level_provenance_refuses_full_rebinding(self):
        original = (self.root / manual.CATALOG).read_bytes()
        try:
            for key in manual.PLAYBOOK_IDS:
                for field in ('verified_at', 'master_sha'):
                    for value in (None, '', True, 'not-valid', '2099-01-01T00:00:00Z'):
                        with self.subTest(playbook=key, field=field, value=value):
                            (self.root / manual.CATALOG).write_bytes(original)
                            packet, scope = self.packet(key)
                            packet['reuse_entries'] = ['group_158']
                            catalog = json.loads(original)
                            if value is None:
                                catalog.pop(field)
                            else:
                                catalog[field] = value
                            self.write(manual.CATALOG, catalog)
                            self.rebind_all(packet, scope)
                            reason = 'catalog_header_' + field + ('_future' if field == 'verified_at' and value == '2099-01-01T00:00:00Z' else '_invalid')
                            with self.assertRaisesRegex(manual.ContractError, reason):
                                manual.lookup_reuse('group_158', self.root)
                            self.rejected(packet, scope, reason)
                            cli = self.cli_fixture(packet, scope)
                            self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                            self.assertEqual(json.loads(cli.stdout)['reason'], reason)
                            self.assertEqual(cli.stderr, '')
            catalog = json.loads(original)
            catalog.update(verified_at='2026-10-09T12:00:00+09:00', master_sha='a' * 40)
            self.write(manual.CATALOG, catalog)
            for key in manual.PLAYBOOK_IDS:
                packet, scope = self.packet(key)
                packet['reuse_entries'] = ['group_158']
                result = self.validate(self.bind(packet), scope)
                self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                self.assertFalse(result['economic_authority'])
        finally:
            (self.root / manual.CATALOG).write_bytes(original)

    def test_accepted_dnr_records_cannot_be_deleted_or_reidentified(self):
        original = (self.root / manual.DNR).read_bytes()
        fields = ('signal', 'mechanism', 'book', 'window')
        registry = json.loads(original)
        self.assertEqual(len(registry['entries']), 21)
        controls = {path: (self.root / path).read_bytes()
                    for path in (manual.MANIFEST, manual.CATALOG)}
        try:
            for index, row in enumerate(registry['entries']):
                for field in ('delete', 'id', *fields):
                    with self.subTest(entry=row['id'], field=field):
                        (self.root / manual.DNR).write_bytes(original)
                        packet, scope = self.packet()
                        packet['do_not_repeat_candidate'] = {k: row[k] for k in fields}
                        changed = copy.deepcopy(registry)
                        if field == 'delete':
                            changed['entries'].pop(index)
                        else:
                            changed['entries'][index][field] += '_changed'
                        self.write(manual.DNR, changed)
                        self.rebind_schema_fixture(packet, scope)
                        self.rejected(packet, scope, 'do_not_repeat_historical_identity_changed')
                        if row['id'] == 'monthly_dd_vix_floor':
                            cli = self.cli_fixture(packet, scope)
                            self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                            self.assertEqual(json.loads(cli.stdout)['reason'], 'do_not_repeat_historical_identity_changed')
                            self.assertEqual(cli.stderr, '')
            changed = copy.deepcopy(registry)
            changed['entries'][0]['evidence'].append('SYNTHETIC_METADATA_ONLY')
            for field in fields:
                changed['entries'][0][field] = ' ' + changed['entries'][0][field].upper() + ' '
            added = copy.deepcopy(registry['entries'][0])
            added['id'] = 'synthetic_additive_record'
            added['signal'] = 'SYNTHETIC_NEW_SIGNAL'
            changed['entries'].append(added)
            self.write(manual.DNR, changed)
            for key in manual.PLAYBOOK_IDS:
                packet, scope = self.packet(key)
                result = self.validate(packet, scope)
                self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                self.assertFalse(result['economic_authority'])
        finally:
            (self.root / manual.DNR).write_bytes(original)
            for path, raw in controls.items():
                (self.root / path).write_bytes(raw)

    def test_new_master_registered_cohort_proof_is_mandatory(self):
        name = 'tests/twelve_private_cohort_smoke.py'
        witness = (ROOT / 'tests/twelve_private_capture_smoke.py').read_text()
        self.assertIn("path = ROOT / 'tests/twelve_private_cohort_smoke.py'", witness)
        self.assertIn(name, manual.required_dependencies('A6_INDEPENDENT_QA', self.root))
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        packet['dependencies'].pop(name)
        scope['dependencies'].pop(name)
        self.rejected(self.rebind_schema_fixture(packet, scope), scope, 'missing_dependency')

    def test_a6_etf_universe_refuses_stale_and_rebound_missing_pin(self):
        name = 'research/etf_holdings_universe_20260520/thematic_etfs.yaml'
        self.assertIn('tests/smoke_test.py',
                      {path for path, _ in registered_validation.DEFAULT_TESTS})
        witness = fixture_dependency_bytes('tests/smoke_test.py', 'HEAD').decode()
        self.assertIn('def test_etf_holdings_overlay_wired()', witness)
        self.assertIn('"thematic_etfs.yaml").exists()', witness)
        self.assertIn(name, manual.required_dependencies('A6_INDEPENDENT_QA', self.root))
        target = self.root / name
        original = target.read_bytes()
        controls = {path: (self.root / path).read_bytes()
                    for path in (manual.MANIFEST, manual.CATALOG)}
        try:
            for attack in ('stale', 'rebound-omission', 'rebound-deletion'):
                with self.subTest(attack=attack):
                    target.write_bytes(original)
                    for path, raw in controls.items():
                        (self.root / path).write_bytes(raw)
                    packet, scope = self.packet('A6_INDEPENDENT_QA')
                    target.write_bytes(original + b'\n')
                    reason = 'dependency_bytes_changed:' + name
                    if attack.startswith('rebound-'):
                        packet['dependencies'].pop(name)
                        scope['dependencies'].pop(name)
                        if attack == 'rebound-deletion':
                            target.unlink()
                        self.rebind_schema_fixture(packet, scope)
                        reason = 'missing_dependency'
                    self.rejected(packet, scope, reason)
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertEqual(json.loads(cli.stdout)['reason'], reason)
                    self.assertEqual(cli.stderr, '')
        finally:
            target.write_bytes(original)
            for path, raw in controls.items():
                (self.root / path).write_bytes(raw)
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        accepted = self.validate(packet, scope)
        cli = self.cli_fixture(packet, scope)
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertEqual(accepted['status'], 'VALIDATED_PREPARE_ONLY')
        self.assertEqual(set(accepted['proof_results'].values()), {'NOT_RUN'})
        for field in ('worker_invoked', 'completed_task', 'economic_authority'):
            self.assertFalse(accepted[field])

    def test_declared_issue_refs_match_metadata_after_full_rebinding(self):
        original = (self.root / manual.CATALOG).read_bytes()
        try:
            for key in manual.PLAYBOOK_IDS:
                for selected in (False, True):
                    for declared in (None, '#999'):
                        with self.subTest(playbook=key, selected=selected, declared=declared):
                            (self.root / manual.CATALOG).write_bytes(original)
                            packet, scope = self.packet(key)
                            catalog = json.loads(original)
                            row = next(row for row in catalog['entries']
                                       if row['entry_id'] == 'group_516')
                            self.assertEqual(set(row['source_metadata']), {'#516'})
                            if declared is None:
                                row.pop('pr_or_group')
                            else:
                                row['pr_or_group'] = declared
                            self.write(manual.CATALOG, catalog)
                            packet['reuse_entries'] = ['group_516'] if selected else []
                            self.rebind_all(packet, scope)
                            with self.assertRaisesRegex(manual.ContractError, 'catalog_issue_reference_identity'):
                                manual.lookup_reuse('group_516', root=self.root)
                            self.rejected(packet, scope, 'catalog_issue_reference_identity')
                            cli = self.cli_fixture(packet, scope)
                            self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                            self.assertEqual(json.loads(cli.stdout)['reason'], 'catalog_issue_reference_identity')
                            self.assertEqual(cli.stderr, '')
        finally:
            (self.root / manual.CATALOG).write_bytes(original)
        catalog = manual.load_catalog(self.root)
        issues = [row for row in catalog['entries'] if row['source_kind'] == 'ISSUE']
        self.assertTrue(issues)
        for row in issues:
            self.assertEqual(set(row['pr_or_group'].split('/')), set(row['source_metadata']))
            self.assertEqual(row['source_heads'], {})
        self.assertTrue(manual.lookup_reuse('group_516', root=self.root)['allowed'])

    def test_manifest_verification_provenance_refuses_full_rebinding(self):
        original = (self.root / manual.MANIFEST).read_bytes()
        try:
            for key in manual.PLAYBOOK_IDS:
                for field in ('verified_at', 'master_sha'):
                    bad = [None, '', True, 'not-valid']
                    bad.append('2099-01-01T00:00:00Z' if field == 'verified_at' else 'A' * 40)
                    for value in bad:
                        with self.subTest(playbook=key, field=field, value=value):
                            (self.root / manual.MANIFEST).write_bytes(original)
                            packet, scope = self.packet(key)
                            manifest = json.loads(original)
                            if value is None:
                                manifest.pop(field)
                            else:
                                manifest[field] = value
                            self.rebind_all(packet, scope, manifest)
                            reason = 'manual_manifest_' + field + ('_future' if value == '2099-01-01T00:00:00Z' else '_invalid')
                            with self.assertRaisesRegex(manual.ContractError, reason):
                                manual.load_playbook(key, self.root)
                            self.rejected(packet, scope, reason)
                            cli = self.cli_fixture(packet, scope)
                            self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                            self.assertEqual(json.loads(cli.stdout)['reason'], reason)
                            self.assertEqual(cli.stderr, '')
            manifest = json.loads(original)
            manifest['verified_at'] = '2026-10-09T12:00:00+09:00'
            manifest['master_sha'] = 'a' * 40
            for key in manual.PLAYBOOK_IDS:
                (self.root / manual.MANIFEST).write_bytes(original)
                packet, scope = self.packet(key)
                self.rebind_all(packet, scope, manifest)
                result = self.validate(packet, scope)
                cli = self.cli_fixture(packet, scope)
                self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
                self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                for field in ('worker_invoked', 'completed_task', 'economic_authority'):
                    self.assertFalse(result[field])
        finally:
            (self.root / manual.MANIFEST).write_bytes(original)

    def test_a6_sec_filing_schedule_semantic_change_requires_new_proof_pins(self):
        name = 'research/sec_13f_filing_schedule.json'
        # Fixed independent consumer witness from registered SEC 13F proof.
        self.assertIn('tests/sec_13f_filing_freshness_smoke.py',
                      {path for path, _ in registered_validation.DEFAULT_TESTS})
        self.assertIn(name, manual.required_dependencies('A6_INDEPENDENT_QA', self.root))
        target = self.root / name
        original = target.read_bytes()
        controls = {path: (self.root / path).read_bytes()
                    for path in (manual.MANIFEST, manual.CATALOG)}
        try:
            packet, scope = self.packet('A6_INDEPENDENT_QA')
            self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
            value = json.loads(original)
            self.assertEqual(value['deadlines'][0]['filing_deadline'], '2026-05-15')
            value['deadlines'][0]['filing_deadline'] = '2026-05-18'
            self.write(name, value)
            self.rejected(packet, scope, 'dependency_bytes_changed:' + name)
            stale = self.cli_fixture(packet, scope)
            self.assertEqual(stale.returncode, 2, stale.stdout + stale.stderr)
            self.assertEqual(json.loads(stale.stdout)['reason'], 'dependency_bytes_changed:' + name)
            self.assertEqual(stale.stderr, '')
            packet['dependencies'].pop(name)
            scope['dependencies'].pop(name)
            self.rebind_schema_fixture(packet, scope)
            self.rejected(packet, scope, 'missing_dependency')
            missing = self.cli_fixture(packet, scope)
            self.assertEqual(missing.returncode, 2, missing.stdout + missing.stderr)
            self.assertEqual(json.loads(missing.stdout)['reason'], 'missing_dependency')
            self.assertEqual(missing.stderr, '')
        finally:
            target.write_bytes(original)
            for path, raw in controls.items():
                (self.root / path).write_bytes(raw)
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        accepted = self.validate(packet, scope)
        self.assertEqual(accepted['status'], 'VALIDATED_PREPARE_ONLY')
        self.assertEqual(set(accepted['proof_results'].values()), {'NOT_RUN'})
        self.assertFalse(accepted['worker_invoked'])
        self.assertFalse(accepted['economic_authority'])

    def test_catalog_historical_ids_refuse_full_hash_rebound_deletion(self):
        baseline = frozenset((
            'group_1',
            'group_158',
            'group_174',
            'group_267',
            'group_400_405',
            'group_423_574',
            'group_459',
            'group_473',
            'group_505',
            'group_510',
            'group_516',
            'group_526',
            'group_531',
            'group_556',
            'group_559',
            'group_560',
            'group_577',
            'group_578',
            'group_582_583_584',
            'group_586',
            'group_591',
            'group_592',
        ))
        self.assertEqual(manual.CATALOG_ACCEPTED_ENTRY_IDS, baseline)
        target = self.root / manual.CATALOG
        original = target.read_bytes()
        self.assertEqual({row['entry_id'] for row in json.loads(original)['entries']}, baseline)
        try:
            for victim in ('group_1', 'group_174', 'ALL'):
                with self.subTest(victim=victim):
                    target.write_bytes(original)
                    packet, scope = self.packet('L0_RESUME_HANDOFF')
                    catalog = json.loads(original)
                    catalog['entries'] = ([] if victim == 'ALL' else
                                          [row for row in catalog['entries']
                                           if row['entry_id'] != victim])
                    self.write(manual.CATALOG, catalog)
                    self.rebind_all(packet, scope)
                    self.rejected(packet, scope, 'catalog_historical_identity_removed')
                    rejected_cli = self.cli_fixture(packet, scope)
                    self.assertEqual(rejected_cli.returncode, 2,
                                     rejected_cli.stdout + rejected_cli.stderr)
                    self.assertEqual(json.loads(rejected_cli.stdout)['reason'],
                                     'catalog_historical_identity_removed')
                    self.assertEqual(rejected_cli.stderr, '')
            target.write_bytes(original)
            catalog = json.loads(original)
            catalog['entries'][0]['capability'] += ' (reviewed metadata correction)'
            self.write(manual.CATALOG, catalog)
            packet, scope = self.packet('L0_RESUME_HANDOFF')
            accepted = self.validate(packet, scope)
            self.assertEqual(accepted['status'], 'VALIDATED_PREPARE_ONLY')
            self.assertFalse(accepted['worker_invoked'])
            self.assertFalse(accepted['completed_task'])
            self.assertFalse(accepted['economic_authority'])
        finally:
            target.write_bytes(original)

    def test_a6_scorecard_required_absorbed_sources_are_all_pinned(self):
        registry = manual.board.read_json(self.root / 'docs/run287_operating_scorecard_sources.json')
        consumed = {row['path'] for row in registry['sources']
                    if row.get('required') is True and row.get('disposition') == 'ABSORBED_SOURCE'}
        self.assertTrue(consumed)
        missing = consumed - set(manual.required_dependencies('A6_INDEPENDENT_QA', self.root))
        self.assertEqual(missing, set())

    def test_a6_scorecard_csvs_refuse_stale_and_rebound_missing_inputs(self):
        from tools import build_run287_operating_scorecard as scorecard
        names = (
            'data_static/run287_operating_scorecard_sources_v1/p4/reserve_mode_metrics.csv',
            'data_static/run287_operating_scorecard_sources_v1/p6/selected_vs_rank_matched_metrics.csv',
        )
        for name in names:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(fixture_dependency_bytes(name, 'HEAD'))
        registry = manual.board.read_json(self.root / 'docs/run287_operating_scorecard_sources.json')
        original_controls = {name: (self.root / name).read_bytes()
                             for name in (manual.MANIFEST, manual.CATALOG)}
        with patch.object(scorecard, 'REPO_ROOT', self.root), \
             patch.object(scorecard, 'CANONICAL_SOURCE_ROOT',
                          (self.root / scorecard.CANONICAL_SOURCE_PREFIX).resolve()):
            bundle, errors = scorecard.verify_canonical_source_bundle(registry)
            self.assertEqual((bundle['status'], errors), ('VERIFIED', []))
            for name in names:
                target = self.root / name
                original = target.read_bytes()
                for attack in ('stale', 'rebound-omission', 'rebound-deletion'):
                    with self.subTest(path=name, attack=attack):
                        try:
                            packet, scope = self.packet('A6_INDEPENDENT_QA')
                            positive = self.cli_fixture(packet, scope)
                            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
                            self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
                            target.write_bytes(original + b'synthetic_unreviewed,0\n')
                            changed, errors = scorecard.verify_canonical_source_bundle(registry)
                            self.assertEqual(changed['status'], 'INTEGRITY_ERROR')
                            self.assertTrue(any('source_hash_mismatch' in value for value in errors))
                            reason = 'dependency_bytes_changed'
                            if attack != 'stale':
                                packet['dependencies'].pop(name, None)
                                scope['dependencies'].pop(name, None)
                                if attack == 'rebound-deletion':
                                    target.unlink()
                                self.rebind_schema_fixture(packet, scope)
                                reason = 'missing_dependency'
                            self.rejected(packet, scope, reason)
                            refused = self.cli_fixture(packet, scope)
                            self.assertEqual(refused.returncode, 2, refused.stdout + refused.stderr)
                            self.assertIn(reason, json.loads(refused.stdout)['reason'])
                            self.assertEqual(refused.stderr, '')
                        finally:
                            target.write_bytes(original)
                            for control, raw in original_controls.items():
                                (self.root / control).write_bytes(raw)
                            restored, errors = scorecard.verify_canonical_source_bundle(registry)
                            self.assertEqual((restored['status'], errors), ('VERIFIED', []))

    def test_documented_a6_command_supplies_independent_review_head(self):
        text = (self.root / 'docs/MANUAL_FOUNDATION_V1.md').read_text()
        commands = re.findall(r'```bash\s*\n(.*?)\n\s*```', text, re.DOTALL)
        a6 = [value for value in commands if '--expected-review-head' in value]
        general = [value for value in commands if '--expected-review-head' not in value]
        self.assertEqual(len(a6), 1)
        self.assertEqual(len(general), 1)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONOPTIMIZE=str(sys.flags.optimize))
        env['PYTHONPATH'] = str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
        replacements = {'/path/task.json': str(self.root / 'packet.json'),
                        '/path/verified_scope.json': str(self.root / 'scope.json'),
                        '<live-master-sha>': BASE, '<implementation-head-sha>': REVIEW_HEAD}

        def run(command, key):
            packet, scope = self.packet(key)
            self.write('packet.json', packet)
            self.write('scope.json', scope)
            argv = [replacements.get(value, value) for value in shlex.split(command.replace('\\\n', ' '))]
            self.assertEqual(argv[:2], ['python', 'tools/manual_foundation.py'])
            argv[:1] = [sys.executable, '-B'] + (['-O'] if sys.flags.optimize else [])
            return subprocess.run(argv, cwd=self.root, env=env, capture_output=True, text=True, timeout=30)

        for command, key in ((a6[0], 'A6_INDEPENDENT_QA'), (general[0], 'L0_RESUME_HANDOFF')):
            positive = run(command, key)
            self.assertEqual(positive.returncode, 0, positive.stdout + positive.stderr)
            value = json.loads(positive.stdout)
            self.assertEqual(value['status'], 'VALIDATED_PREPARE_ONLY')
            self.assertEqual(set(value['proof_results'].values()), {'NOT_RUN'})
            self.assertFalse(value['worker_invoked'])
            self.assertFalse(value['completed_task'])
            self.assertFalse(value['economic_authority'])
            self.assertEqual(positive.stderr, '')
        missing = run(general[0], 'A6_INDEPENDENT_QA')
        self.assertEqual(missing.returncode, 2, missing.stdout + missing.stderr)
        self.assertEqual(json.loads(missing.stdout)['reason'], 'expected_review_head_required')
        self.assertEqual(missing.stderr, '')

    def test_sparse_fixture_uses_exact_git_blob_and_keeps_input_refusals(self):
        name = 'manifests/fullrun/run287_canonical_a_20260731.json'
        missing = ROOT / name
        source_commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                               cwd=ROOT, text=True).strip()
        canonical = subprocess.check_output(['git', 'show', source_commit + ':' + name], cwd=ROOT)
        read_bytes, copyfile = Path.read_bytes, shutil.copyfile

        def sparse_read(path):
            if path == missing:
                raise FileNotFoundError(str(path))
            return read_bytes(path)

        def sparse_copy(source, target, **kwargs):
            if Path(source) == missing:
                raise FileNotFoundError(str(source))
            return copyfile(source, target, **kwargs)

        fixture = type(self)(self._testMethodName)
        self.addCleanup(fixture.doCleanups)
        with patch.object(Path, 'read_bytes', autospec=True, side_effect=sparse_read), \
             patch.object(shutil, 'copyfile', side_effect=sparse_copy):
            fixture.setUp()
        with self.assertRaises(FileNotFoundError):
            fixture_dependency_bytes('tests/synthetic-absent-fixture-input.json', source_commit)
        with patch.object(Path, 'read_bytes', autospec=True, return_value=b'changed working bytes'), \
             patch.object(subprocess, 'check_output') as git_read:
            self.assertEqual(fixture_dependency_bytes(name, source_commit), b'changed working bytes')
            git_read.assert_not_called()
        with patch.object(Path, 'is_symlink', return_value=True), \
             patch.object(subprocess, 'check_output') as git_read, \
             self.assertRaises(FileNotFoundError):
            fixture_dependency_bytes(name, source_commit)
        git_read.assert_not_called()
        for mode, kind in ((b'120000', b'blob'), (b'040000', b'tree')):
            with self.subTest(mode=mode), \
                 patch.object(Path, 'read_bytes', autospec=True, side_effect=sparse_read), \
                 patch.object(subprocess, 'check_output',
                              return_value=mode + b' ' + kind + b' ' + b'a' * 40 +
                                           b'\t' + name.encode() + b'\0'), \
                 self.assertRaises(FileNotFoundError):
                fixture_dependency_bytes(name, source_commit)
        target = fixture.root / name
        self.assertEqual(target.read_bytes(), canonical)
        packet, scope = fixture.packet('A6_INDEPENDENT_QA')
        self.assertEqual(fixture.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
        cli = fixture.cli_fixture(packet, scope)
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertEqual(cli.stderr, '')
        for result in (fixture.validate(packet, scope), json.loads(cli.stdout)):
            self.assertFalse(result['worker_invoked'])
            self.assertFalse(result['completed_task'])
            self.assertFalse(result['economic_authority'])
            self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
        target.write_bytes(canonical + b'\n')
        fixture.rejected(packet, scope, 'dependency_bytes_changed')
        cli = fixture.cli_fixture(packet, scope)
        self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
        self.assertTrue(json.loads(cli.stdout)['reason'].startswith('dependency_bytes_changed:'))
        self.assertEqual(cli.stderr, '')
        del packet['dependencies'][name]
        del scope['dependencies'][name]
        target.unlink()
        fixture.rejected(fixture.rebind_schema_fixture(packet, scope), scope, 'missing_dependency')
        cli = fixture.cli_fixture(packet, scope)
        self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
        self.assertEqual(json.loads(cli.stdout)['reason'], 'missing_dependency')
        self.assertEqual(cli.stderr, '')

    def packet(self, key='L0_RESUME_HANDOFF', *, propose_successor=False):
        _, playbook = manual.load_playbook(key, self.root, propose_successor=propose_successor)
        dependencies = {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()
                        for name in manual.required_dependencies(key, self.root,
                                                                  propose_successor=propose_successor)}
        review_identity = (dict(repository=manual.REVIEW_REPOSITORY, pr_number=593, head_sha=REVIEW_HEAD)
                           if key == 'A6_INDEPENDENT_QA' else None)
        scope = dict(base_sha=BASE, review_identity=copy.deepcopy(review_identity),
                     owner=playbook['owner'], dependencies=dependencies,
                     allowed_files=[], authority=manual.board.AUTHORITY.copy(), authority_tier='T2_PREPARE')
        packet = dict(schema_version='manual-task-packet-v1', task_key='SYNTHETIC-MANUAL-TEST',
            packet_sha256='', playbook_id=key, playbook_version=playbook['playbook_version'],
            playbook_sha256=playbook['playbook_sha256'], owner=playbook['owner'], base_sha=BASE,
            review_identity=copy.deepcopy(review_identity),
            dependencies=copy.deepcopy(dependencies), allowed_files=[],
            toolbox_refs=playbook['toolbox_refs'].copy(), proof_set=playbook['proof_set'].copy(),
            authority=manual.board.AUTHORITY.copy(), authority_tier='T2_PREPARE', mode=playbook['mode'],
            stop_condition=playbook['process']['stop_condition'].copy(),
            output_receipt=dict(schema_version='R1000_WORKER_RESULT_V1', reference='SYNTHETIC_RECEIPT_ONLY'),
            reuse_entries=[])
        return self.bind(packet), scope

    def bind(self, packet):
        packet['packet_sha256'] = independent_hash(packet, 'packet_sha256')
        return packet

    def rebind_dependency(self, packet, scope, name):
        digest = hashlib.sha256((self.root / name).read_bytes()).hexdigest()
        packet['dependencies'][name] = scope['dependencies'][name] = digest
        return self.bind(packet)

    def validate(self, packet, scope, expected_review_head=None, *, propose_successor=False):
        if expected_review_head is None and packet['playbook_id'] == 'A6_INDEPENDENT_QA':
            expected_review_head = REVIEW_HEAD
        return manual.validate_packet(packet, scope, expected_base=BASE,
                                      expected_review_head=expected_review_head, root=self.root,
                                      propose_successor=propose_successor)

    def rejected(self, packet, scope, reason=None, *, propose_successor=False):
        with self.assertRaises(manual.ContractError) as caught:
            self.validate(packet, scope, propose_successor=propose_successor)
        if reason:
            self.assertIn(reason, str(caught.exception))

    def reviewed_fixture_anchors(self, manifest, accepted=None):
        # Synthetic independent approval context, captured BEFORE mutations.
        # Never overwrite the actual reviewed baseline or read an input anchor.
        trusted = copy.deepcopy(manual.VERSION_ANCHOR_CONTENT)
        for row in manifest['playbooks']:
            identity = (row['playbook_id'], row['playbook_version'])
            if accepted is None or identity in accepted:
                raw = json.dumps({k: v for k, v in row.items()
                                  if k not in ('status', 'playbook_sha256')},
                                 sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
                trusted.setdefault(identity, hashlib.sha256(raw).hexdigest())
        return patch.object(manual, 'VERSION_ANCHOR_CONTENT', trusted)

    def successor_fixture(self, manifest, key, version):
        row = next(r for r in manifest['playbooks'] if r['playbook_id'] == key and r['status'] == 'CURRENT')
        old = copy.deepcopy(row)
        old['status'] = 'SUPERSEDED'
        manifest['playbooks'].append(old)
        row.update(playbook_version=version, supersedes=old['playbook_version'])
        manifest['current_versions'][key] = version
        return row

    def cli_fixture(self, packet, scope, *, propose_successor=False):
        self.write('packet.json', packet)
        self.write('scope.json', scope)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONOPTIMIZE=str(sys.flags.optimize))
        env['PYTHONPATH'] = str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
        prefix = [sys.executable, '-B'] + (['-O'] if sys.flags.optimize else [])
        command = prefix + [str(self.root / 'tools/manual_foundation.py'), '--packet',
                            str(self.root / 'packet.json'), '--scope', str(self.root / 'scope.json'),
                            '--expected-base', BASE, '--expected-review-head', REVIEW_HEAD]
        if propose_successor:
            command.append('--propose-successor')
        return subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)

    def test_a6_auto_learning_package_refuses_stale_and_rebound_omission(self):
        # Literal import witnesses stay independent of the validator's list.
        names = (
            'auto_learning_v2/__init__.py',
            'auto_learning_v2/anomaly_detector.py',
            'auto_learning_v2/challenger_backtester.py',
            'auto_learning_v2/counterfactual_tester.py',
            'auto_learning_v2/hypothesis_generator.py',
            'auto_learning_v2/novelty_regime_detector.py',
            'auto_learning_v2/policy_candidate_builder.py',
            'auto_learning_v2/policy_grammar.py',
            'auto_learning_v2/promotion_governor.py',
        )
        for name in names:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / name).read_bytes())
        for name in names:
            with self.subTest(name=name):
                target = self.root / name
                original = target.read_bytes()
                try:
                    packet, scope = self.packet('A6_INDEPENDENT_QA')
                    self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
                    changed = b'pass\n'
                    compile(changed, name, 'exec')  # Syntax only; never execute economic code.
                    target.write_bytes(changed)
                    self.rejected(packet, scope, 'dependency_bytes_changed')
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertTrue(json.loads(cli.stdout)['reason'].startswith('dependency_bytes_changed:'))
                    self.assertEqual(cli.stderr, '')
                    fresh, fresh_scope = self.packet('A6_INDEPENDENT_QA')
                    cli = self.cli_fixture(fresh, fresh_scope)
                    self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
                    self.assertEqual(cli.stderr, '')
                    for result in (self.validate(fresh, fresh_scope), json.loads(cli.stdout)):
                        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                        self.assertFalse(result['worker_invoked'])
                        self.assertFalse(result['completed_task'])
                        self.assertFalse(result['economic_authority'])
                        self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                    del fresh['dependencies'][name]
                    del fresh_scope['dependencies'][name]
                    for delete_file in (False, True):
                        if delete_file:
                            target.unlink()
                        self.rejected(self.rebind_schema_fixture(fresh, fresh_scope),
                                      fresh_scope, 'missing_dependency')
                        cli = self.cli_fixture(fresh, fresh_scope)
                        self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                        self.assertEqual(json.loads(cli.stdout)['reason'], 'missing_dependency')
                        self.assertEqual(cli.stderr, '')
                finally:
                    target.write_bytes(original)

    def test_deep_json_decode_returns_blocked_input_without_traceback(self):
        packet, scope = self.packet()
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONOPTIMIZE=str(sys.flags.optimize))
        env['PYTHONPATH'] = str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
        prefix = [sys.executable, '-B'] + (['-O'] if sys.flags.optimize else [])
        arguments = [str(self.root / 'tools/manual_foundation.py'), '--packet',
                     str(self.root / 'packet.json'), '--scope', str(self.root / 'scope.json'),
                     '--expected-base', BASE]
        deep = '[' * 10000 + '0' + ']' * 10000
        for name in ('packet.json', 'scope.json'):
            with self.subTest(name=name):
                self.write('packet.json', packet)
                self.write('scope.json', scope)
                (self.root / name).write_text(deep)
                stdout, stderr = io.StringIO(), io.StringIO()
                with patch.object(sys, 'argv', arguments), \
                     contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    self.assertEqual(manual.main(), 2)
                result = json.loads(stdout.getvalue())
                self.assertEqual(result['status'], 'BLOCKED_INPUT')
                self.assertFalse(result['worker_invoked'])
                self.assertEqual(stderr.getvalue(), '')
                cli = subprocess.run(prefix + arguments, env=env, capture_output=True,
                                     text=True, timeout=30)
                self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                self.assertEqual(json.loads(cli.stdout)['status'], 'BLOCKED_INPUT')
                self.assertFalse(json.loads(cli.stdout)['worker_invoked'])
                self.assertEqual(cli.stderr, '')
        for value in ([], None, 1, 'text', True):
            cli = self.cli_fixture(value, scope)
            self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
            self.assertEqual(json.loads(cli.stdout)['status'], 'BLOCKED_INPUT')
            self.assertEqual(cli.stderr, '')
        cli = self.cli_fixture(packet, scope)
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertEqual(json.loads(cli.stdout)['status'], 'VALIDATED_PREPARE_ONLY')
        self.assertFalse(json.loads(cli.stdout)['worker_invoked'])
        self.assertEqual(cli.stderr, '')

    def test_allowed_file_parent_is_directory_or_prospective(self):
        for name in ('AGENTS.md/result.json', 'AGENTS.md/new/sub/result.json'):
            for location in ('packet', 'scope', 'both'):
                with self.subTest(name=name, location=location):
                    packet, scope = self.packet()
                    if location in ('packet', 'both'):
                        packet['allowed_files'] = [name]
                    if location in ('scope', 'both'):
                        scope['allowed_files'] = [name]
                    self.rejected(self.rebind_schema_fixture(packet, scope), scope,
                                  'allowed_file_parent_not_directory')
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertEqual(json.loads(cli.stdout)['reason'], 'allowed_file_parent_not_directory')
                    self.assertEqual(cli.stderr, '')
        for name in ('AGENTS.md', 'docs/new-result.json', 'docs/new/sub/result.json'):
            with self.subTest(positive=name):
                packet, scope = self.packet()
                packet['allowed_files'] = scope['allowed_files'] = [name]
                self.rebind_schema_fixture(packet, scope)
                self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
                cli = self.cli_fixture(packet, scope)
                self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
                self.assertFalse(json.loads(cli.stdout)['worker_invoked'])
                self.assertFalse(json.loads(cli.stdout)['economic_authority'])
                self.assertEqual(cli.stderr, '')
        packet, scope = self.packet()
        packet['allowed_files'] = scope['allowed_files'] = ['docs']
        self.rejected(self.rebind_schema_fixture(packet, scope), scope, 'allowed_file_is_directory')

    def test_a6_candidate_proof_modules_refuse_stale_and_rebound_omission(self):
        for name in ('research/a3_candidate_packet_v1.py', 'research/candidate_registry_v1.py'):
            with self.subTest(name=name):
                target = self.root / name
                original = target.read_bytes()
                try:
                    packet, scope = self.packet('A6_INDEPENDENT_QA')
                    self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
                    target.write_bytes(b'pass\n')
                    compile(target.read_bytes(), name, 'exec')
                    self.rejected(packet, scope, 'dependency_bytes_changed')
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertTrue(json.loads(cli.stdout)['reason'].startswith('dependency_bytes_changed:'))
                    self.assertEqual(cli.stderr, '')
                    fresh, fresh_scope = self.packet('A6_INDEPENDENT_QA')
                    cli = self.cli_fixture(fresh, fresh_scope)
                    self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
                    for result in (self.validate(fresh, fresh_scope), json.loads(cli.stdout)):
                        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                        self.assertFalse(result['worker_invoked'])
                        self.assertFalse(result['completed_task'])
                        self.assertFalse(result['economic_authority'])
                        self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                    del fresh['dependencies'][name]
                    del fresh_scope['dependencies'][name]
                    for deleted in (False, True):
                        if deleted:
                            target.unlink()
                            # This catalog also names the now-absent source.
                            # Retain its declared hash; rebind every other input.
                            self.rebind_all(fresh, fresh_scope)
                        else:
                            self.rebind_schema_fixture(fresh, fresh_scope)
                        self.rejected(fresh, fresh_scope, 'missing_dependency')
                        cli = self.cli_fixture(fresh, fresh_scope)
                        self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                        self.assertEqual(json.loads(cli.stdout)['reason'], 'missing_dependency')
                        self.assertEqual(cli.stderr, '')
                finally:
                    target.write_bytes(original)

    def test_replay_reuse_imports_stale_and_omitted_hashes_fail_closed(self):
        names = ('tools/nav_metrics_v2.py', 'tools/run_weekly_evaluation.py',
                 'tools/execution_cost_model.py', 'tools/reserve_asset_policy.py')
        canonical = (self.root / manual.CATALOG).read_bytes()
        for name in names:
            with self.subTest(name=name):
                target = self.root / name
                original = target.read_bytes()
                try:
                    packet, scope = self.packet()
                    packet['reuse_entries'] = ['group_158']
                    self.bind(packet)
                    self.assertTrue(manual.lookup_reuse('group_158', self.root)['allowed'])
                    self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
                    target.write_bytes(b'pass\n')
                    compile(target.read_bytes(), name, 'exec')
                    self.rejected(packet, scope, 'catalog_dependency_changed')
                    with self.assertRaisesRegex(manual.ContractError, 'catalog_dependency_changed'):
                        manual.lookup_reuse('group_158', self.root)
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertEqual(cli.stderr, '')
                    self.rebind_schema_fixture(packet, scope)
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
                    for result in (self.validate(packet, scope), json.loads(cli.stdout)):
                        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                        self.assertFalse(result['worker_invoked'])
                        self.assertFalse(result['completed_task'])
                        self.assertFalse(result['economic_authority'])
                        self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                    rebound_catalog = (self.root / manual.CATALOG).read_bytes()
                    for selected in manual.PLAYBOOK_IDS:
                        for reuse in ([], ['group_158']):
                            (self.root / manual.CATALOG).write_bytes(rebound_catalog)
                            catalog = manual.board.read_json(self.root / manual.CATALOG)
                            row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_158')
                            row['dependency_hashes'].pop(name, None)
                            self.write(manual.CATALOG, catalog)
                            fresh, fresh_scope = self.packet(selected)
                            fresh['reuse_entries'] = reuse
                            self.rejected(self.rebind_schema_fixture(fresh, fresh_scope),
                                          fresh_scope, 'catalog_unpinned_reuse_path')
                            cli = self.cli_fixture(fresh, fresh_scope)
                            self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                            self.assertEqual(json.loads(cli.stdout)['reason'], 'catalog_unpinned_reuse_path')
                            self.assertEqual(cli.stderr, '')
                finally:
                    target.write_bytes(original)
                    (self.root / manual.CATALOG).write_bytes(canonical)
        # Closure follows actual consumer paths despite row renaming or use of
        # the risk-grid subprocess wrapper without the replay in its path list.
        for renamed in (False, True):
            try:
                catalog = manual.board.read_json(self.root / manual.CATALOG)
                row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_158')
                row['dependency_hashes'].pop('tools/nav_metrics_v2.py', None)
                if renamed:
                    row['entry_id'] = 'SYNTHETIC_RENAMED_REPLAY_ROUTE'
                else:
                    row['current_equivalent'] = row['toolbox_refs'] = ['tools/run_broker_position_risk_grid_sweep.py']
                    row['dependency_hashes'].pop('tools/run_broker_ledger_replay.py', None)
                self.write(manual.CATALOG, catalog)
                packet, scope = self.packet()
                self.rejected(self.rebind_schema_fixture(packet, scope), scope, 'catalog_unpinned_reuse_path')
            finally:
                (self.root / manual.CATALOG).write_bytes(canonical)

    def test_grid_subprocess_closure_refuses_stale_and_rebound_omissions(self):
        # Literal subprocess/import witnesses, independent of the recipe.
        names = ('tools/run_broker_position_risk_replay.py',
                 'tools/run_position_aware_risk_replay.py', 'tools/historical_replay_lib.py')
        canonical = (self.root / manual.CATALOG).read_bytes()
        for name in names:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            original = (ROOT / name).read_bytes()
            target.write_bytes(original)
            with self.subTest(name=name):
                try:
                    packet, scope = self.packet()
                    packet['reuse_entries'] = ['group_158']
                    self.bind(packet)
                    self.assertTrue(manual.lookup_reuse('group_158', self.root)['allowed'])
                    self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
                    target.write_bytes(b'pass\n')
                    compile(target.read_bytes(), name, 'exec')
                    self.rejected(packet, scope, 'catalog_dependency_changed')
                    with self.assertRaisesRegex(manual.ContractError, 'catalog_dependency_changed'):
                        manual.lookup_reuse('group_158', self.root)
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertTrue(json.loads(cli.stdout)['reason'].startswith('catalog_dependency_changed:'))
                    self.assertEqual(cli.stderr, '')
                    # A freshly verified dependency may be rebound; preflight
                    # still grants no worker execution or economic authority.
                    self.rebind_schema_fixture(packet, scope)
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
                    self.assertEqual(cli.stderr, '')
                    for result in (self.validate(packet, scope), json.loads(cli.stdout)):
                        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                        self.assertFalse(result['worker_invoked'])
                        self.assertFalse(result['completed_task'])
                        self.assertFalse(result['economic_authority'])
                        self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                    rebound_catalog = (self.root / manual.CATALOG).read_bytes()
                    for selected in manual.PLAYBOOK_IDS:
                        for reuse in ([], ['group_158']):
                            (self.root / manual.CATALOG).write_bytes(rebound_catalog)
                            catalog = manual.board.read_json(self.root / manual.CATALOG)
                            row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_158')
                            row['dependency_hashes'].pop(name, None)
                            self.write(manual.CATALOG, catalog)
                            fresh, fresh_scope = self.packet(selected)
                            fresh['reuse_entries'] = reuse
                            self.rejected(self.rebind_schema_fixture(fresh, fresh_scope),
                                          fresh_scope, 'catalog_unpinned_reuse_path')
                            cli = self.cli_fixture(fresh, fresh_scope)
                            self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                            self.assertEqual(json.loads(cli.stdout)['reason'], 'catalog_unpinned_reuse_path')
                            self.assertEqual(cli.stderr, '')
                    for renamed in (False, True):
                        (self.root / manual.CATALOG).write_bytes(rebound_catalog)
                        catalog = manual.board.read_json(self.root / manual.CATALOG)
                        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_158')
                        row['dependency_hashes'].pop(name, None)
                        if renamed:
                            row['entry_id'] = 'SYNTHETIC_RENAMED_GRID_ROUTE'
                        else:
                            row['current_equivalent'] = row['toolbox_refs'] = [
                                'tools/run_broker_position_risk_grid_sweep.py']
                        self.write(manual.CATALOG, catalog)
                        fresh, fresh_scope = self.packet()
                        fresh['reuse_entries'] = [row['entry_id']]
                        self.rejected(self.rebind_schema_fixture(fresh, fresh_scope),
                                      fresh_scope, 'catalog_unpinned_reuse_path')
                        cli = self.cli_fixture(fresh, fresh_scope)
                        self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                        self.assertEqual(json.loads(cli.stdout)['reason'], 'catalog_unpinned_reuse_path')
                        self.assertEqual(cli.stderr, '')
                finally:
                    target.write_bytes(original)
                    (self.root / manual.CATALOG).write_bytes(canonical)

    def test_reader_catalog_imports_refuse_stale_and_rebound_omissions(self):
        # Actual Reader imports/default registry; independent literal witnesses.
        names = ('data_static/research_dataset_registry_v1.json',
                 'tools/long_history_lake.py', 'tools/macro_history_sources.py',
                 'tools/macro_research_checkpoint.py', 'tools/run_data_freshness_contract.py',
                 'r1000_legacy_input_guard.py')
        canonical = (self.root / manual.CATALOG).read_bytes()
        for entry in ('group_423_574', 'group_591'):
            for name in names:
                with self.subTest(entry=entry, name=name):
                    target = self.root / name
                    original = target.read_bytes()
                    try:
                        packet, scope = self.packet()
                        packet['reuse_entries'] = [entry]
                        self.bind(packet)
                        self.assertTrue(manual.lookup_reuse(entry, self.root)['allowed'])
                        target.write_bytes(b'pass\n' if name.endswith('.py') else b'{}\n')
                        if name.endswith('.py'):
                            compile(target.read_bytes(), name, 'exec')
                        self.rejected(packet, scope, 'catalog_dependency_changed')
                        cli = self.cli_fixture(packet, scope)
                        self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                        self.assertEqual(cli.stderr, '')
                        self.rebind_schema_fixture(packet, scope)
                        result = self.validate(packet, scope)
                        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                        self.assertFalse(result['worker_invoked'])
                        self.assertFalse(result['completed_task'])
                        self.assertFalse(result['economic_authority'])
                        self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                        rebound = (self.root / manual.CATALOG).read_bytes()
                        for selected in manual.PLAYBOOK_IDS:
                            for reuse in ([], [entry]):
                                (self.root / manual.CATALOG).write_bytes(rebound)
                                catalog = manual.board.read_json(self.root / manual.CATALOG)
                                row = next(r for r in catalog['entries'] if r['entry_id'] == entry)
                                row['dependency_hashes'].pop(name, None)
                                self.write(manual.CATALOG, catalog)
                                fresh, fresh_scope = self.packet(selected)
                                fresh['reuse_entries'] = reuse
                                self.rejected(self.rebind_schema_fixture(fresh, fresh_scope),
                                              fresh_scope, 'catalog_unpinned_reuse_path')
                                cli = self.cli_fixture(fresh, fresh_scope)
                                self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                                self.assertEqual(json.loads(cli.stdout)['reason'],
                                                 'catalog_unpinned_reuse_path')
                                self.assertEqual(cli.stderr, '')
                    finally:
                        target.write_bytes(original)
                        (self.root / manual.CATALOG).write_bytes(canonical)

    def test_other_reuse_imports_and_unreviewed_python_refuse_rebinding(self):
        # Local import witnesses from the other existing advertised capabilities.
        cases = (('group_560', 'research/a3_candidate_packet_v1.py'),
                 ('group_556', 'tools/collect_earnings_estimates_finnhub.py'),
                 ('group_577', 'tools/chameleon_market_context_v2.py'),
                 ('group_592', 'aggressive/data_alpaca.py'),
                 ('group_592', 'r1000_risk_sensing.py'),
                 ('group_423_574', 'tools/macro_research_cycle.py'),
                 ('group_423_574', 'docs/macro_indicator_registry.json'))
        canonical = (self.root / manual.CATALOG).read_bytes()
        for entry, name in cases:
            with self.subTest(entry=entry, name=name):
                target = self.root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                if not target.is_file():
                    target.write_bytes((ROOT / name).read_bytes())
                original = target.read_bytes()
                try:
                    packet, scope = self.packet()
                    packet['reuse_entries'] = [entry]
                    self.bind(packet)
                    self.assertTrue(manual.lookup_reuse(entry, self.root)['allowed'])
                    target.write_bytes(b'pass\n' if name.endswith('.py') else b'{}\n')
                    if name.endswith('.py'):
                        compile(target.read_bytes(), name, 'exec')
                    self.rejected(packet, scope, 'catalog_dependency_changed')
                    self.rebind_schema_fixture(packet, scope)
                    self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
                    catalog = manual.board.read_json(self.root / manual.CATALOG)
                    row = next(r for r in catalog['entries'] if r['entry_id'] == entry)
                    row['entry_id'] = 'SYNTHETIC_RENAMED_CAPABILITY'
                    row['dependency_hashes'].pop(name, None)
                    self.write(manual.CATALOG, catalog)
                    self.rejected(self.rebind_schema_fixture(packet, scope), scope,
                                  'catalog_unpinned_reuse_path')
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertEqual(cli.stderr, '')
                finally:
                    target.write_bytes(original)
                    (self.root / manual.CATALOG).write_bytes(canonical)
        packet, scope = self.packet()
        # An editable row cannot supply an empty reviewed recipe for new code.
        name = 'tools/SYNTHETIC_UNREVIEWED_CAPABILITY.py'
        (self.root / name).write_bytes(b'pass\n')
        catalog = manual.board.read_json(self.root / manual.CATALOG)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
        row['current_equivalent'] = row['toolbox_refs'] = [name]
        row['dependency_hashes'] = {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()}
        self.write(manual.CATALOG, catalog)
        self.rejected(self.rebind_schema_fixture(packet, scope), scope, 'catalog_unpinned_reuse_path')
        cli = self.cli_fixture(packet, scope)
        self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
        self.assertEqual(cli.stderr, '')
        (self.root / manual.CATALOG).write_bytes(canonical)
        for row in manual.load_catalog(self.root)['entries']:
            if row['classification'] == 'REUSE_NOW':
                self.assertTrue(manual.lookup_reuse(row['entry_id'], self.root)['allowed'])

    def test_all_three_manuals_have_current_hash_and_four_layers(self):
        for key, owner in manual.PLAYBOOK_IDS.items():
            _, row = manual.load_playbook(key, self.root)
            self.assertEqual(row['owner'], owner)
            self.assertEqual(row['playbook_sha256'], independent_hash(row, 'playbook_sha256'))
            for layer in ('process', 'toolbox_refs', 'proof', 'learning'):
                self.assertTrue(row[layer])
            self.assertGreaterEqual(len(row['proof']['checks']), 5)
            self.assertLessEqual(len(row['proof']['checks']), 10)
            packet, scope = self.packet(key)
            result = self.validate(packet, scope)
            self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
            self.assertFalse(result['worker_invoked'])
            self.assertFalse(result['completed_task'])
            self.assertFalse(result['economic_authority'])
            self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})

    def test_stale_version_and_hash_refused_even_after_packet_rebinding(self):
        for field, value in [('playbook_version', '0.0.1'), ('playbook_sha256', 'a' * 64)]:
            packet, scope = self.packet()
            packet[field] = value
            self.rejected(self.bind(packet), scope, 'stale_playbook')

    def test_packet_hash_binds_task_and_every_scope_field(self):
        for field, value in [('task_key', 'RENAMED'), ('playbook_sha256', 'a' * 64),
                             ('output_receipt', {'schema_version': 'R1000_WORKER_RESULT_V1', 'reference': 'OTHER'})]:
            packet, scope = self.packet()
            packet[field] = value
            self.rejected(packet, scope)

    def test_wrong_base_cannot_be_self_attested(self):
        packet, scope = self.packet()
        packet['base_sha'] = scope['base_sha'] = 'b' * 40
        self.rejected(self.bind(packet), scope, 'wrong_base')

    def test_wrong_dependency_cannot_be_rehashed(self):
        packet, scope = self.packet()
        packet['dependencies']['AGENTS.md'] = 'a' * 64
        self.rejected(self.bind(packet), scope, 'wrong_dependency')
        scope['dependencies']['AGENTS.md'] = 'a' * 64
        self.rejected(packet, scope, 'dependency_bytes_changed')

    def test_missing_required_dependency_even_in_matching_scope(self):
        packet, scope = self.packet()
        del packet['dependencies']['AGENTS.md']
        del scope['dependencies']['AGENTS.md']
        self.rejected(self.bind(packet), scope, 'missing_dependency')

    def test_same_head_dirty_toolbox_bytes_are_rejected(self):
        packet, scope = self.packet()
        with (self.root / 'tools/run_agent_board.py').open('a') as stream:
            stream.write('\n# dirty same-head fixture\n')
        self.rejected(packet, scope, 'dependency_bytes_changed')

    def test_authority_escalation_all_existing_flags_and_extra_fields(self):
        for flag in ('execute', 'target', 'broker', 'scheduler', 'promotion', 'peer_dispatch'):
            packet, scope = self.packet()
            packet['authority'][flag] = scope['authority'][flag] = True
            self.rejected(self.bind(packet), scope)
        packet, scope = self.packet()
        packet['authority']['fullrun'] = True
        self.rejected(self.bind(packet), scope)

    def test_boolean_authority_cannot_be_numeric_zero(self):
        packet, scope = self.packet()
        packet['authority']['execute'] = 0
        self.rejected(self.bind(packet), scope)

    def test_authority_tier_cannot_exceed_independent_scope(self):
        packet, scope = self.packet()
        scope['authority_tier'] = 'T0_READ'
        self.rejected(packet, scope, 'authority_tier_escalation')
        packet['authority_tier'] = 'T3_REVERSIBLE_WRITE'
        self.rejected(self.bind(packet), scope)

    def test_source_write_scope_cannot_expand(self):
        packet, scope = self.packet()
        packet['allowed_files'] = ['r1000_config.py']
        self.rejected(self.bind(packet), scope, 'file_scope_escalation')

    def test_a6_remains_read_only_even_if_scope_lists_write_paths(self):
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        packet['allowed_files'] = scope['allowed_files'] = ['r1000_config.py']
        self.rejected(self.bind(packet), scope, 'qa_source_write')

    def test_owner_mode_toolbox_proof_and_stop_condition_cannot_be_waived(self):
        for field, value in [('owner', 'A1'), ('mode', 'READ_ONLY'), ('toolbox_refs', []),
                             ('proof_set', ['ONLY_ONE']), ('stop_condition', ['NO_STOP'])]:
            packet, scope = self.packet()
            packet[field] = value
            self.rejected(self.bind(packet), scope)

    def test_exact_paths_reject_traversal_globs_aliases_and_symlinks(self):
        for path in ('../AGENTS.md', '/tmp/AGENTS.md', 'docs/*', 'docs/./a', 'C:\\a', 'docs//a'):
            with self.assertRaises(manual.ContractError):
                manual.path_at(self.root, path)
        alias = self.root / 'alias'
        alias.symlink_to(self.root / 'docs', target_is_directory=True)
        with self.assertRaises(manual.ContractError):
            manual.path_at(self.root, 'alias/pr_reuse_catalog.json')

    def test_superseded_playbook_never_selected(self):
        manifest = manual.board.read_json(self.root / manual.MANIFEST)
        old = copy.deepcopy(manifest['playbooks'][0])
        old['status'] = 'SUPERSEDED'
        old['playbook_sha256'] = independent_hash(old, 'playbook_sha256')
        current = manifest['playbooks'][0]
        current['playbook_version'] = '1.1.0'
        current['supersedes'] = '1.0.0'
        current['playbook_sha256'] = independent_hash(current, 'playbook_sha256')
        manifest['current_versions'][current['playbook_id']] = '1.1.0'
        manifest['playbooks'].append(old)
        self.write(manual.MANIFEST, manifest)
        with self.reviewed_fixture_anchors(manifest):
            packet, scope = self.packet()
            self.assertEqual(packet['playbook_version'], '1.1.0')
            packet['playbook_version'] = old['playbook_version']
            packet['playbook_sha256'] = old['playbook_sha256']
            self.rejected(self.bind(packet), scope, 'stale_playbook')

    def test_hash_valid_manifest_with_wrong_current_mapping_refused(self):
        manifest = manual.board.read_json(self.root / manual.MANIFEST)
        manifest['current_versions']['L0_RESUME_HANDOFF'] = '9.0.0'
        self.write(manual.MANIFEST, manifest)
        with self.assertRaises(manual.ContractError):
            manual.load_playbook('L0_RESUME_HANDOFF', self.root)

    def test_duplicate_current_manual_or_tampered_manual_refused(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for mutate in ('duplicate', 'tamper'):
            manifest = copy.deepcopy(original)
            if mutate == 'duplicate':
                manifest['playbooks'].append(copy.deepcopy(manifest['playbooks'][0]))
            else:
                manifest['playbooks'][0]['process']['steps'].clear()
            self.write(manual.MANIFEST, manifest)
            with self.assertRaises(manual.ContractError):
                manual.load_playbook('L0_RESUME_HANDOFF', self.root)

    def test_only_requested_seed_groups_and_issue_pr_distinction(self):
        catalog = manual.load_catalog(self.root)
        expected = {1,158,174,267,400,405,423,574,459,473,505,510,516,526,531,556,559,560,577,578,582,583,584,586,591,592}
        actual = {int(n[1:]) for row in catalog['entries'] for n in row['source_metadata']}
        self.assertEqual(actual, expected)
        for row in catalog['entries']:
            if row['source_kind'] == 'ISSUE':
                self.assertEqual(row['source_heads'], {})
        self.assertEqual(catalog['do_not_repeat_registry'], manual.DNR)

    def test_historical_archive_worktree_limit_before_allocation(self):
        path = self.root / HISTORICAL_LAKE_FIXTURE
        for size in (0, 64 * 1024 + 1):
            with self.subTest(size=size):
                path.write_bytes(b'x' * size)
                with patch.dict(globals(), {'ROOT': self.root}):
                    with patch('os.open', side_effect=AssertionError('archive opened')):
                        with self.assertRaisesRegex(ValueError, 'historical_fixture_size'):
                            fixture_dependency_bytes(HISTORICAL_LAKE_FIXTURE, 'HEAD')

    def test_historical_archive_growth_stays_bounded(self):
        path = self.root / HISTORICAL_LAKE_FIXTURE
        path.write_bytes(b'x')
        original = os.fdopen
        requests = []
        class Handle:
            def __init__(self, handle): self.handle = handle
            def __enter__(self): return self
            def __exit__(self, *args): self.handle.close()
            def read(self, size=-1):
                requests.append(size)
                with path.open('ab') as output:
                    output.write(b'x' * (64 * 1024 + 10))
                return self.handle.read(size)
        def wrap(*args, **kwargs): return Handle(original(*args, **kwargs))
        with patch.dict(globals(), {'ROOT': self.root}):
            with patch('os.fdopen', side_effect=wrap):
                with self.assertRaisesRegex(ValueError, 'historical_fixture_size'):
                    fixture_dependency_bytes(HISTORICAL_LAKE_FIXTURE, 'HEAD')
        self.assertEqual(requests, [64 * 1024 + 1])

    def test_historical_archive_sparse_size_precedes_blob(self):
        (self.root / HISTORICAL_LAKE_FIXTURE).unlink()
        oid = 'a' * 40
        entry = b'100644 blob ' + oid.encode() + b'\t' + HISTORICAL_LAKE_FIXTURE.encode() + b'\0'
        def metadata(command, **kwargs):
            if command[1] == 'ls-tree': return entry
            self.assertEqual(command, ['git', 'cat-file', '-s', oid])
            return b'65537\n'
        with patch.dict(globals(), {'ROOT': self.root}):
            with patch('subprocess.check_output', side_effect=metadata):
                with patch('subprocess.Popen', side_effect=AssertionError('blob opened')):
                    with self.assertRaisesRegex(ValueError, 'historical_fixture_size'):
                        fixture_dependency_bytes(HISTORICAL_LAKE_FIXTURE, 'HEAD')

    def test_historical_archive_sparse_valid_read_is_capped(self):
        (self.root / HISTORICAL_LAKE_FIXTURE).unlink()
        oid = 'a' * 40
        entry = b'100644 blob ' + oid.encode() + b'\t' + HISTORICAL_LAKE_FIXTURE.encode() + b'\0'
        def metadata(command, **kwargs):
            if command[1] == 'ls-tree': return entry
            self.assertEqual(command, ['git', 'cat-file', '-s', oid])
            return b'7\n'
        with patch.dict(globals(), {'ROOT': self.root}):
            with patch('subprocess.check_output', side_effect=metadata):
                with patch('subprocess.Popen') as popen:
                    process = popen.return_value
                    process.stdout.read.return_value = b'archive'
                    process.wait.return_value = 0
                    process.poll.return_value = 0
                    self.assertEqual(fixture_dependency_bytes(HISTORICAL_LAKE_FIXTURE, 'HEAD'), b'archive')
                    self.assertEqual(popen.call_args.args[0], ['git', 'cat-file', 'blob', oid])
                    process.stdout.read.assert_called_once_with(64 * 1024 + 1)
                    process.stdout.close.assert_called_once_with()

    def test_historical_catalog_fixture_only_reverses_exact_checkout_conversion(self):
        self.use_historical_reader_catalog()
        frozen = b'# synthetic historical fixture\noriginal bytes\n'
        expected = hashlib.sha256(frozen).hexdigest()
        self.assertEqual(historical_catalog_fixture_bytes(frozen, expected), frozen)
        self.assertEqual(historical_catalog_fixture_bytes(frozen.replace(b'\n', b'\r\n'), expected), frozen)
        changed = frozen.replace(b'original', b'changed').replace(b'\n', b'\r\n')
        self.assertEqual(historical_catalog_fixture_bytes(changed, expected), changed)
        for name in ('docs/RESEARCH_DATA_ACCESS.md', 'r1000_legacy_input_guard.py'):
            row = next(row for row in manual.load_catalog(self.root)['entries']
                       if row['entry_id'] == 'group_423_574')
            target = self.root / name
            original = target.read_bytes()
            before = (self.root / manual.CATALOG).read_bytes()
            try:
                changed = original.replace(b'\n', b'\r\n') + b'# changed synthetic fixture\r\n'
                target.write_bytes(historical_catalog_fixture_bytes(changed, row['dependency_hashes'][name]))
                with self.assertRaisesRegex(manual.ContractError, 'catalog_dependency_changed:' + re.escape(name)):
                    manual.lookup_reuse('group_423_574', self.root)
                self.assertEqual((self.root / manual.CATALOG).read_bytes(), before)
            finally:
                target.write_bytes(original)

    def test_historical_reader_positives_keep_original_catalog_pins(self):
        active = (ROOT / manual.CATALOG).read_bytes()
        self.use_historical_reader_catalog()
        before = (self.root / manual.CATALOG).read_bytes()
        for name, (expected, _, _) in HISTORICAL_READER_INPUTS.items():
            self.assertEqual(hashlib.sha256((self.root / name).read_bytes()).hexdigest(), expected)
        for entry in ('group_423_574', 'group_591'):
            self.assertTrue(manual.lookup_reuse(entry, self.root)['allowed'])
        self.assertEqual((self.root / manual.CATALOG).read_bytes(), before)
        self.assertEqual((ROOT / manual.CATALOG).read_bytes(), active)

    def test_historical_feature_positive_keeps_original_pins_and_refuses_current_bytes(self):
        active = (ROOT / manual.CATALOG).read_bytes()
        snapshot = (self.root / manual.CATALOG).read_bytes()
        row = next(row for row in manual.load_catalog(self.root)['entries'] if row['entry_id'] == 'group_577')
        originals = {
            'r1000_features.py': '96decfe3eef4bfe7fc92e2419ffddf9d1ffc54be685c98d96f270a551cd568da',
            'r1000_pipeline.py': '8384a59befc11ebbb80fe9235e40dadc6fddefe3a8f2cf6adebf47621d1a3880',
        }
        self.assertTrue(manual.lookup_reuse('group_577', self.root)['allowed'])
        for name, expected in originals.items():
            target = self.root / name
            frozen = target.read_bytes()
            self.assertEqual(row['dependency_hashes'][name], expected)
            self.assertEqual(hashlib.sha256(frozen).hexdigest(), expected)
            current = fixture_dependency_bytes(name, 'HEAD')
            for changed in (current, frozen + b'\n# synthetic modified historical operand\n'):
                target.write_bytes(changed)
                try:
                    if hashlib.sha256(changed).hexdigest() != expected:
                        with self.assertRaisesRegex(manual.ContractError, 'catalog_dependency_changed:' + re.escape(name)):
                            manual.lookup_reuse('group_577', self.root)
                    else:
                        self.assertTrue(manual.lookup_reuse('group_577', self.root)['allowed'])
                    self.assertEqual((self.root / manual.CATALOG).read_bytes(), snapshot)
                    self.assertEqual((ROOT / manual.CATALOG).read_bytes(), active)
                finally:
                    target.write_bytes(frozen)

    def test_historical_feature_shallow_fallback_is_bounded_and_exact(self):
        name = 'r1000_pipeline.py'
        blob, size, expected = HISTORICAL_FEATURE_INPUTS[name]
        missing = subprocess.CalledProcessError(128, ['git', 'cat-file', '-s', blob])
        with patch.object(subprocess, 'check_output', side_effect=missing):
            raw = historical_feature_fixture_bytes(name, 'HEAD')
            self.assertEqual(len(raw), size)
            self.assertEqual(hashlib.sha256(raw).hexdigest(), expected)
            for original, (_, original_size, original_sha) in HISTORICAL_FEATURE_INPUTS.items():
                shallow = historical_feature_fixture_bytes(original, 'HEAD')
                self.assertEqual(len(shallow), original_size)
                self.assertEqual(hashlib.sha256(shallow).hexdigest(), original_sha)
            for bad in (None, b'a' * (512 * 1024 + 1), b'!invalid-base64',
                        base64.b64encode(b'corrupt gzip bytes')):
                with self.subTest(archive_type=type(bad).__name__), \
                     patch.dict(globals(), {'HISTORICAL_FEATURE_PIPELINE_GZIP': bad}), \
                     self.assertRaises((ValueError, OSError, EOFError)):
                    historical_feature_fixture_bytes(name, 'HEAD')
            # Even a self-consistently rebound compressed bomb cannot exceed
            # the fixed original uncompressed read bound or pass its raw hash.
            bomb = gzip.compress(b'x' * (size + 1), mtime=0)
            original_read = gzip.GzipFile.read
            reads = []
            def bounded_read(handle, count=-1):
                reads.append(count)
                return original_read(handle, count)
            with patch.dict(globals(), {
                    'HISTORICAL_FEATURE_PIPELINE_GZIP': base64.b64encode(bomb),
                    'HISTORICAL_FEATURE_PIPELINE_COMPRESSED_SIZE': len(bomb),
                    'HISTORICAL_FEATURE_PIPELINE_COMPRESSED_SHA256': hashlib.sha256(bomb).hexdigest()}), \
                 patch.object(gzip.GzipFile, 'read', bounded_read), \
                 self.assertRaisesRegex(ValueError, 'historical_feature_fixture_hash'):
                historical_feature_fixture_bytes(name, 'HEAD')
            self.assertEqual(reads, [size + 1])
        with patch.object(subprocess, 'check_output', return_value=str(size + 1).encode()), \
             patch.object(subprocess, 'Popen') as body, \
             self.assertRaisesRegex(ValueError, 'historical_feature_fixture_size'):
            historical_feature_fixture_bytes(name, 'HEAD')
        body.assert_not_called()
        with patch.object(subprocess, 'check_output', return_value=str(size).encode()), \
             patch.object(subprocess, 'Popen') as body:
            body.return_value.stdout.read.return_value = b'wrong immutable blob'
            body.return_value.wait.return_value = body.return_value.poll.return_value = 0
            with self.assertRaisesRegex(ValueError, 'historical_feature_fixture_hash'):
                historical_feature_fixture_bytes(name, 'HEAD')
            body.return_value.stdout.read.assert_called_once_with(size + 1)
            body.return_value.stdout.close.assert_called_once_with()
        with self.assertRaisesRegex(ValueError, 'historical_feature_fixture_name'):
            historical_feature_fixture_bytes('unapproved-code.py', 'HEAD')

    def test_historical_reader_archive_hash_and_size_are_bounded(self):
        for name, (expected, size, archive) in HISTORICAL_READER_INPUTS.items():
            self.assertEqual(len(historical_reader_fixture_bytes(name)), size)
            for bad in (b'!not_base64', base64.b64encode(b'not gzip'),
                        base64.b64encode(gzip.compress(b'x' * (size + 1), mtime=0)),
                        b'a' * (128 * 1024 + 1)):
                with self.subTest(name=name, bytes=len(bad)):
                    with patch.dict(HISTORICAL_READER_INPUTS, {name: (expected, size, bad)}):
                        with self.assertRaises((ValueError, OSError, EOFError)):
                            historical_reader_fixture_bytes(name)

    def test_historical_reader_positives_do_not_recertify_changed_inputs(self):
        self.use_historical_reader_catalog()
        catalog_before = (self.root / manual.CATALOG).read_bytes()
        for name in HISTORICAL_READER_INPUTS:
            frozen = historical_reader_fixture_bytes(name)
            target = self.root / name
            current = fixture_dependency_bytes(name, 'HEAD')
            entries = ('group_423_574', 'group_591') if name.endswith('.py') else ('group_591',)
            for changed in (current, frozen + b'\n# SYNTHETIC_CHANGED_HISTORICAL_INPUT\n'):
                with self.subTest(name=name, current=changed == current):
                    target.write_bytes(changed)
                    try:
                        for entry in entries:
                            if hashlib.sha256(changed).hexdigest() != hashlib.sha256(frozen).hexdigest():
                                with self.assertRaisesRegex(manual.ContractError, 'catalog_dependency_changed:' + name):
                                    manual.lookup_reuse(entry, self.root)
                            else:
                                self.assertTrue(manual.lookup_reuse(entry, self.root)['allowed'])
                        self.assertEqual((self.root / manual.CATALOG).read_bytes(), catalog_before)
                    finally:
                        target.write_bytes(frozen)

    def test_historical_lake_positive_does_not_recertify_changed_source(self):
        self.use_historical_reader_catalog()
        name = 'tools/long_history_lake.py'
        frozen = historical_lake_fixture_bytes()
        target = self.root / name
        self.assertEqual(target.read_bytes(), frozen)
        catalog_before = (self.root / manual.CATALOG).read_bytes()
        current = fixture_dependency_bytes(name, 'HEAD')
        for changed in (current, frozen + b'\n# SYNTHETIC_VALID_PYTHON_CHANGE\n'):
            with self.subTest(current_source=changed == current):
                target.write_bytes(changed)
                differs = hashlib.sha256(changed).hexdigest() != HISTORICAL_LAKE_SHA256
                for entry in ('group_423_574', 'group_591'):
                    if differs:
                        with self.assertRaisesRegex(manual.ContractError, 'catalog_dependency_changed:' + name):
                            manual.lookup_reuse(entry, self.root)
                    else:
                        self.assertTrue(manual.lookup_reuse(entry, self.root)['allowed'])
                if differs:
                    packet, scope = self.packet('A1_SOURCE_ADMISSION_REFRESH')
                    packet['reuse_entries'] = ['group_591']
                    # Rebind the task's current bytes, never the historical catalog.
                    self.rejected(self.rebind_all(packet, scope), scope,
                                  'catalog_dependency_changed:' + name)
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertEqual(json.loads(cli.stdout)['reason'], 'catalog_dependency_changed:' + name)
                    self.assertEqual(cli.stderr, '')
                self.assertEqual((self.root / manual.CATALOG).read_bytes(), catalog_before)
        target.write_bytes(frozen)

    def test_historical_fixture_is_bound_in_a6_proof_inputs(self):
        name = HISTORICAL_LAKE_FIXTURE
        self.assertIn(name, manual.required_dependencies('A6_INDEPENDENT_QA', self.root))
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        path = self.root / name
        original = path.read_bytes()
        path.write_bytes(original + b'changed')
        self.rejected(packet, scope, 'dependency_bytes_changed:' + name)
        path.write_bytes(original)
        packet['dependencies'].pop(name)
        scope['dependencies'].pop(name)
        self.rejected(self.rebind_all(packet, scope), scope, 'missing_dependency')

    def test_historical_sec_positive_does_not_recertify_current_source(self):
        catalog_before = (self.root / manual.CATALOG).read_bytes()
        self.assertTrue(manual.lookup_reuse('group_577', self.root)['allowed'])
        for name, frozen in historical_sec_fixture_bytes().items():
            current = fixture_dependency_bytes(name, 'HEAD')
            target = self.root / name
            for changed in (current, frozen + b'\n# changed historical source\n'):
                target.write_bytes(changed)
                if hashlib.sha256(changed).hexdigest() != HISTORICAL_SEC_FILES[name]:
                    with self.assertRaisesRegex(manual.ContractError, 'catalog_dependency_changed:' + name):
                        manual.lookup_reuse('group_577', self.root)
                else:
                    self.assertTrue(manual.lookup_reuse('group_577', self.root)['allowed'])
                self.assertEqual((self.root / manual.CATALOG).read_bytes(), catalog_before)
            target.write_bytes(frozen)

    def test_historical_sec_fixture_is_hash_bounded_and_mandatory(self):
        name = HISTORICAL_SEC_FIXTURE
        self.assertIn(name, manual.required_dependencies('A6_INDEPENDENT_QA', self.root))
        original = (self.root / name).read_bytes()
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        (self.root / name).write_bytes(original + b'changed')
        self.rejected(packet, scope, 'dependency_bytes_changed:' + name)
        (self.root / name).write_bytes(original)
        packet['dependencies'].pop(name)
        scope['dependencies'].pop(name)
        self.rejected(self.rebind_all(packet, scope), scope, 'missing_dependency')
        with patch('gzip.GzipFile') as stream:
            stream.return_value.__enter__.return_value.read.return_value = b'changed'
            with self.assertRaisesRegex(ValueError, 'historical_sec_fixture_hash'):
                historical_sec_fixture_bytes()

    def test_historical_a3_positive_does_not_recertify_current_source(self):
        catalog_before = (self.root / manual.CATALOG).read_bytes()
        entries = {r['entry_id']: r for r in manual.load_catalog(self.root)['entries']}
        self.assertFalse(manual.lookup_reuse('group_400_405', self.root)['allowed'])
        for name, frozen in historical_a3_fixture_bytes().items():
            target = self.root / name
            current = fixture_dependency_bytes(name, 'HEAD')
            for changed in (current, frozen + b'\n# changed historical A3 source\n'):
                target.write_bytes(changed)
                if hashlib.sha256(changed).hexdigest() != HISTORICAL_A3_FILES[name]:
                    for entry in ('group_400_405', 'group_516', 'group_560'):
                        if name in entries[entry]['dependency_hashes']:
                            with self.assertRaisesRegex(manual.ContractError, 'catalog_dependency_changed:' + name):
                                manual.lookup_reuse(entry, self.root)
                self.assertEqual((self.root / manual.CATALOG).read_bytes(), catalog_before)
            target.write_bytes(frozen)
        self.assertTrue(manual.lookup_reuse('group_516', self.root)['allowed'])
        self.assertTrue(manual.lookup_reuse('group_560', self.root)['allowed'])
        self.assertFalse(manual.lookup_reuse('group_400_405', self.root)['allowed'])
        with self.assertRaisesRegex(manual.ContractError, 'catalog_dependency_changed:'):
            manual.lookup_reuse('group_516', ROOT)

    def test_historical_a3_fixture_is_hash_bounded_and_mandatory(self):
        name = HISTORICAL_A3_FIXTURE
        self.assertIn(name, manual.required_dependencies('A6_INDEPENDENT_QA', self.root))
        original = (self.root / name).read_bytes()
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        (self.root / name).write_bytes(original + b'changed')
        self.rejected(packet, scope, 'dependency_bytes_changed:' + name)
        (self.root / name).write_bytes(original)
        packet['dependencies'].pop(name)
        scope['dependencies'].pop(name)
        self.rejected(self.rebind_all(packet, scope), scope, 'missing_dependency')
        with patch('gzip.GzipFile') as stream:
            stream.return_value.__enter__.return_value.read.return_value = b'changed'
            with self.assertRaisesRegex(ValueError, 'historical_a3_fixture_hash'):
                historical_a3_fixture_bytes()

    def test_reuse_now_requires_actual_current_bytes(self):
        for entry in ('group_423_574', 'group_591'):
            self.assertTrue(manual.lookup_reuse(entry, self.root)['allowed'])
        for name, old in (('tools/long_history_lake.py', historical_lake_fixture_bytes()),
                          ('tools/macro_history_sources.py',
                           historical_reader_fixture_bytes('tools/macro_history_sources.py'))):
            target = self.root / name
            original = target.read_bytes()
            target.write_bytes(old)
            try:
                for entry in ('group_423_574', 'group_591'):
                    with self.assertRaisesRegex(manual.ContractError, 'catalog_dependency_changed:' + re.escape(name)):
                        manual.lookup_reuse(entry, self.root)
            finally:
                target.write_bytes(original)
        (self.root / 'tools/research_data_access.py').write_text('CHANGED')
        with self.assertRaisesRegex(manual.ContractError, 'catalog_dependency_changed'):
            manual.lookup_reuse('group_591', self.root)

    def test_selective_port_and_historical_are_not_automatic_reuse(self):
        live_catalog = (ROOT / manual.CATALOG).read_bytes()
        for key, classification in (('group_400_405', 'SELECTIVE_PORT'),):
            row = next(row for row in manual.load_catalog(self.root)['entries']
                       if row['entry_id'] == key)
            self.assertEqual(row['classification'], classification)
            # Reverse checkout newlines only when the original, unchanged pin
            # proves the exact historical bytes; never rebind a catalog pin.
            for name, expected_sha in row['dependency_hashes'].items():
                target = self.root / name
                target.write_bytes(historical_catalog_fixture_bytes(target.read_bytes(), expected_sha))
            result = manual.lookup_reuse(key, self.root)
            self.assertIs(result['allowed'], False)
            self.assertIs(result['economic_authority'], False)
            packet, scope = self.packet()
            packet['reuse_entries'] = [key]
            self.rejected(self.bind(packet), scope, 'catalog_reuse_not_allowed')

        # The causal ledger extraction advances current source, not the old
        # SELECTIVE_PORT/HISTORICAL_LESSON dependency authority. A precise
        # stale-operand refusal is non-admission, never a reason to repin it.
        for key, classification in (('group_586', 'SELECTIVE_PORT'),
                                    ('group_267', 'HISTORICAL_LESSON'),
                                    ('group_582_583_584', 'SELECTIVE_PORT')):
            row = next(row for row in manual.load_catalog(self.root)['entries']
                       if row['entry_id'] == key)
            self.assertEqual(row['classification'], classification)
            for name, expected_sha in row['dependency_hashes'].items():
                target = self.root / name
                target.write_bytes(historical_catalog_fixture_bytes(target.read_bytes(), expected_sha))
            name = 'tools/run_broker_ledger_replay.py'
            self.assertNotEqual(manual.board.file_hash(self.root / name), row['dependency_hashes'][name])
            with self.assertRaisesRegex(manual.ContractError,
                                        r'^catalog_dependency_changed:tools/run_broker_ledger_replay\.py$'):
                manual.lookup_reuse(key, self.root)
            packet, scope = self.packet()
            packet['reuse_entries'] = [key]
            self.rejected(self.bind(packet), scope, 'catalog_dependency_changed:' + name)

        # group_1 keeps its historical config pin when the current engine epoch
        # advances. Its earlier typed dependency refusal is also non-admission,
        # not an allowed=false result that this test can index into.
        historical = next(row for row in manual.load_catalog(self.root)['entries']
                          if row['entry_id'] == 'group_1')
        self.assertEqual(historical['classification'], 'HISTORICAL_LESSON')
        self.assertNotEqual(manual.board.file_hash(self.root / 'r1000_config.py'),
                            historical['dependency_hashes']['r1000_config.py'])
        with self.assertRaisesRegex(manual.ContractError,
                                    r'^catalog_dependency_changed:r1000_config\.py$'):
            manual.lookup_reuse('group_1', self.root)
        packet, scope = self.packet()
        packet['reuse_entries'] = ['group_1']
        self.rejected(self.bind(packet), scope, 'catalog_dependency_changed:r1000_config.py')
        self.assertEqual((ROOT / manual.CATALOG).read_bytes(), live_catalog)

    def test_superseded_catalog_usage_refused(self):
        catalog = manual.load_catalog(self.root)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
        row.update(classification='SUPERSEDED', superseded_by='group_423_574')
        self.write(manual.CATALOG, catalog)
        packet, scope = self.packet()
        packet['reuse_entries'] = ['group_591']
        self.rejected(self.bind(packet), scope, 'catalog_superseded')

    def test_do_not_repeat_lookup_uses_canonical_registry(self):
        lookup = manual.lookup_reuse('group_174', self.root)
        self.assertFalse(lookup['allowed'])
        self.assertEqual(lookup['blocked_registry_ids'], ['broad_gross_floor'])
        registry = manual.board.read_json(self.root / manual.DNR)
        row = next(r for r in registry['entries'] if r['id'] == 'broad_gross_floor')
        packet, scope = self.packet()
        packet['do_not_repeat_candidate'] = {k: row[k] for k in ('signal', 'mechanism', 'book', 'window')}
        self.rejected(self.bind(packet), scope, 'BLOCKED_DO_NOT_REPEAT')

    def test_catalog_label_cannot_bypass_canonical_do_not_repeat(self):
        catalog = manual.load_catalog(self.root)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_174')
        row['classification'] = 'REUSE_NOW'
        self.write(manual.CATALOG, catalog)
        packet, scope = self.packet()
        packet['reuse_entries'] = ['group_174']
        self.rejected(self.bind(packet), scope, 'catalog_unpinned_reuse_path')

        # Supply a reviewed recipe so the canonical DNR boundary is exercised
        # independently of the earlier unreviewed-capability refusal.
        path = 'tools/nav_metrics_v2.py'
        row['current_equivalent'] = row['toolbox_refs'] = [path]
        row['dependency_hashes'][path] = hashlib.sha256((self.root / path).read_bytes()).hexdigest()
        self.write(manual.CATALOG, catalog)
        lookup = manual.lookup_reuse('group_174', self.root)
        self.assertFalse(lookup['allowed'])
        self.assertEqual(lookup['blocked_registry_ids'], ['broad_gross_floor'])
        packet, scope = self.packet()
        packet['reuse_entries'] = ['group_174']
        self.rejected(self.bind(packet), scope, 'catalog_reuse_not_allowed')
        cli = self.cli_fixture(packet, scope)
        self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
        self.assertEqual(json.loads(cli.stdout)['status'], 'BLOCKED_INPUT')
        self.assertEqual(json.loads(cli.stdout)['reason'], 'catalog_reuse_not_allowed')
        self.assertEqual(cli.stderr, '')
        packet['reuse_entries'] = ['group_158']
        result = self.validate(self.bind(packet), scope)
        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
        self.assertFalse(result['economic_authority'])
        self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})

    def test_catalog_change_invalidates_existing_packet(self):
        packet, scope = self.packet()
        catalog = manual.load_catalog(self.root)
        catalog['entries'][0]['next_use'] = 'UPDATED'
        self.write(manual.CATALOG, catalog)
        self.rejected(packet, scope, 'dependency_bytes_changed')

    def test_duplicate_and_nonfinite_json_refused(self):
        path = self.root / 'invalid.json'
        for text in ('{"task_key":"a","task_key":"b"}', '{"x":NaN}'):
            path.write_text(text)
            with self.assertRaises(manual.ContractError):
                manual.board.read_json(path)

    def test_a6_review_identity_accepts_exact_verified_head(self):
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        result = self.validate(packet, scope, REVIEW_HEAD)
        self.assertEqual(result['review_identity']['head_sha'], REVIEW_HEAD)

    def test_a6_old_review_head_refused_after_live_head_moves(self):
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        with self.assertRaisesRegex(manual.ContractError, 'stale_review_head'):
            self.validate(packet, scope, MOVED_REVIEW_HEAD)

    def test_common_lessons_ledger_is_required_for_a1_and_a6(self):
        for key in ('A1_SOURCE_ADMISSION_REFRESH', 'A6_INDEPENDENT_QA'):
            self.assertIn('docs/AGENT_SHARED_LESSONS_LEDGER.md',
                          manual.required_dependencies(key, self.root))
            packet, scope = self.packet(key)
            self.validate(packet, scope)

    def test_lessons_ledger_change_invalidates_old_packet(self):
        packet, scope = self.packet('A1_SOURCE_ADMISSION_REFRESH')
        with (self.root / 'docs/AGENT_SHARED_LESSONS_LEDGER.md').open('a') as stream:
            stream.write('\n# NEW DURABLE LESSON\n')
        self.rejected(packet, scope, 'dependency_bytes_changed')

    def test_superseded_classification_with_successor_is_valid_but_not_reusable(self):
        catalog = manual.load_catalog(self.root)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
        row.update(classification='SUPERSEDED', superseded_by='group_423_574')
        self.write(manual.CATALOG, catalog)
        manual.load_catalog(self.root)
        with self.assertRaisesRegex(manual.ContractError, 'catalog_superseded'):
            manual.lookup_reuse('group_591', self.root)

    def test_reuse_now_with_superseded_by_is_invalid_catalog(self):
        catalog = manual.load_catalog(self.root)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
        row['superseded_by'] = 'group_423_574'
        self.write(manual.CATALOG, catalog)
        with self.assertRaisesRegex(manual.ContractError, 'catalog_supersedes_invariant'):
            manual.load_catalog(self.root)

    def test_do_not_repeat_coverage_and_semantic_exceptions_are_preserved(self):
        registry = manual.board.read_json(self.root / manual.DNR)
        row = next(r for r in registry['entries'] if r['id'] == 'broad_gross_floor')
        base = {k: row[k] for k in ('signal', 'mechanism', 'book', 'window')}
        for exception in (
            dict(component_coverage_increase_pp=5.0),
            dict(semantics_changed=True, change_note='Different application semantics')
        ):
            packet, scope = self.packet()
            packet['do_not_repeat_candidate'] = {**base, **exception}
            result = self.validate(self.bind(packet), scope)
            self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')

    def test_do_not_repeat_invalid_exception_still_blocks(self):
        registry = manual.board.read_json(self.root / manual.DNR)
        row = next(r for r in registry['entries'] if r['id'] == 'broad_gross_floor')
        packet, scope = self.packet()
        packet['do_not_repeat_candidate'] = {
            **{k: row[k] for k in ('signal', 'mechanism', 'book', 'window')},
            'semantics_changed': True, 'change_note': '   '
        }
        self.rejected(self.bind(packet), scope, 'BLOCKED_DO_NOT_REPEAT')

    def test_prospective_explicit_allowed_file_is_permitted(self):
        packet, scope = self.packet()
        future = 'docs/future_manual_output.json'
        packet['allowed_files'] = scope['allowed_files'] = [future]
        result = self.validate(self.bind(packet), scope)
        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
        self.assertFalse((self.root / future).exists())

    def test_existing_directory_cannot_be_allowed_file_scope(self):
        packet, scope = self.packet()
        packet['allowed_files'] = scope['allowed_files'] = ['docs']
        self.rejected(self.bind(packet), scope, 'allowed_file_is_directory')

    def test_current_catalog_pr_issue_provenance_is_structurally_valid(self):
        catalog = manual.load_catalog(self.root)
        for row in catalog['entries']:
            if row['source_kind'] == 'ISSUE':
                self.assertEqual(row['source_heads'], {})
                self.assertTrue(all(meta['kind'] == 'ISSUE' for meta in row['source_metadata'].values()))
            else:
                self.assertEqual(set(row['source_heads']), set(row['source_metadata']))
                self.assertTrue(all(meta['kind'] == 'PR' for meta in row['source_metadata'].values()))

    def test_fake_issue_head_or_pr_kind_metadata_is_rejected(self):
        original = manual.load_catalog(self.root)
        for mutate in ('head', 'kind'):
            catalog = copy.deepcopy(original)
            row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_505')
            if mutate == 'head':
                row['source_heads'] = {'#505': 'a' * 40}
                reason = 'catalog_issue_has_source_head'
            else:
                row['source_metadata']['#505']['kind'] = 'PR'
                reason = 'catalog_source_identity'
            self.write(manual.CATALOG, catalog)
            with self.assertRaisesRegex(manual.ContractError, reason):
                manual.load_catalog(self.root)
        self.write(manual.CATALOG, original)

    def test_reuse_now_consumed_paths_are_all_hash_pinned(self):
        catalog = manual.load_catalog(self.root)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
        consumed = set(row['current_equivalent']) | set(row['toolbox_refs'])
        self.assertTrue(consumed.issubset(row['dependency_hashes']))
        self.assertTrue(manual.lookup_reuse('group_591', self.root)['allowed'])

    def test_reuse_now_unpinned_consumed_path_is_rejected(self):
        catalog = manual.load_catalog(self.root)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
        row['toolbox_refs'].append('AGENTS.md')
        self.write(manual.CATALOG, catalog)
        with self.assertRaisesRegex(manual.ContractError, 'catalog_unpinned_reuse_path'):
            manual.load_catalog(self.root)

    def test_playbook_successor_version_must_increase(self):
        manifest = manual.board.read_json(self.root / manual.MANIFEST)
        current = manifest['playbooks'][0]
        old = copy.deepcopy(current)
        old['status'] = 'SUPERSEDED'
        old['playbook_sha256'] = independent_hash(old, 'playbook_sha256')
        current['playbook_version'] = '1.1.0'
        current['supersedes'] = '1.0.0'
        current['playbook_sha256'] = independent_hash(current, 'playbook_sha256')
        manifest['current_versions'][current['playbook_id']] = '1.1.0'
        manifest['playbooks'].append(old)
        self.write(manual.MANIFEST, manifest)
        _, row = manual.load_playbook(current['playbook_id'], self.root, propose_successor=True)
        self.assertEqual(row['playbook_version'], '1.1.0')

    def test_playbook_version_downgrade_or_live_predecessor_is_rejected(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for case in ('downgrade', 'predecessor_current'):
            manifest = copy.deepcopy(original)
            current = manifest['playbooks'][0]
            old = copy.deepcopy(current)
            if case == 'downgrade':
                old['playbook_version'] = '1.0.0'
                old['status'] = 'SUPERSEDED'
                old['playbook_sha256'] = independent_hash(old, 'playbook_sha256')
                current['playbook_version'] = '0.9.0'
                current['supersedes'] = '1.0.0'
                reason = 'playbook_version_not_increasing'
            else:
                old['playbook_version'] = '0.9.0'
                old['status'] = 'HISTORICAL'
                old['playbook_sha256'] = independent_hash(old, 'playbook_sha256')
                current['playbook_version'] = '1.0.0'
                current['supersedes'] = '0.9.0'
                reason = 'predecessor_not_superseded'
            current['playbook_sha256'] = independent_hash(current, 'playbook_sha256')
            manifest['current_versions'][current['playbook_id']] = current['playbook_version']
            manifest['playbooks'].append(old)
            self.write(manual.MANIFEST, manifest)
            with self.assertRaisesRegex(manual.ContractError, reason):
                manual.load_playbook(current['playbook_id'], self.root)
        self.write(manual.MANIFEST, original)

    def test_reuse_now_future_expiry_is_allowed(self):
        catalog = manual.load_catalog(self.root)
        row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
        row['expiry'] = '2099-01-01T00:00:00Z'
        self.write(manual.CATALOG, catalog)
        self.assertTrue(manual.lookup_reuse('group_591', self.root)['allowed'])

    def test_reuse_now_past_or_invalid_expiry_is_rejected(self):
        original = manual.load_catalog(self.root)
        for expiry, reason in (
            ('2000-01-01T00:00:00Z', 'catalog_reuse_expired'),
            ('not-a-time', 'catalog_expiry_invalid'),
        ):
            catalog = copy.deepcopy(original)
            row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
            row['expiry'] = expiry
            self.write(manual.CATALOG, catalog)
            with self.assertRaisesRegex(manual.ContractError, reason):
                manual.load_catalog(self.root)
        self.write(manual.CATALOG, original)

    def test_semantic_version_core_accepts_canonical_integer_components(self):
        for value, expected in (
            ('0.0.0', (0, 0, 0)), ('0.1.0', (0, 1, 0)), ('1.0.0', (1, 0, 0)),
            ('1.10.3', (1, 10, 3)), ('10.2.15', (10, 2, 15)),
        ):
            with self.subTest(version=value):
                self.assertEqual(manual.semantic_version(value), expected)

    def test_semantic_version_core_refuses_malformed_or_extended_versions(self):
        for value in ('00.0.0', '01.1.0', '1.01.0', '1.1.00', '1..0', '1.0',
                      '1.0.0.0', 'v1.0.0', '+1.0.0', '1.0.0-rc.1', '1.0.0+build',
                      '１.０.０', '1.0.0\n', None, 100):
            with self.subTest(version=value):
                with self.assertRaisesRegex(manual.ContractError, 'invalid_playbook_version'):
                    manual.semantic_version(value)

    def test_zero_padded_successor_is_refused_with_fully_rebound_packet(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for version in ('00.0.0', '01.1.0', '1.01.0', '1.1.00'):
            with self.subTest(version=version):
                self.write(manual.MANIFEST, original)
                packet, scope = self.packet()
                manifest = copy.deepcopy(original)
                current = manifest['playbooks'][0]
                old = copy.deepcopy(current)
                old['status'] = 'SUPERSEDED'
                old['playbook_sha256'] = independent_hash(old, 'playbook_sha256')
                current.update(playbook_version=version, supersedes='1.0.0')
                current['playbook_sha256'] = independent_hash(current, 'playbook_sha256')
                manifest['playbooks'].append(old)
                manifest['current_versions'][current['playbook_id']] = version
                self.write(manual.MANIFEST, manifest)
                packet.update(playbook_version=version, playbook_sha256=current['playbook_sha256'])
                dependency = hashlib.sha256((self.root / manual.MANIFEST).read_bytes()).hexdigest()
                packet['dependencies'][manual.MANIFEST] = scope['dependencies'][manual.MANIFEST] = dependency
                self.rejected(self.bind(packet), scope, 'invalid_playbook_version')
        self.write(manual.MANIFEST, original)

    def test_successor_numeric_tuple_order_and_reflexive_replacement(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for previous, successor, allowed in (
            ('1.9.0', '1.10.0', True), ('1.0.9', '1.0.10', True),
            ('1.10.0', '1.9.0', False), ('1.0.0', '1.0.0', False),
        ):
            with self.subTest(previous=previous, successor=successor):
                manifest = copy.deepcopy(original)
                current = manifest['playbooks'][0]
                anchor = copy.deepcopy(current)
                old = copy.deepcopy(current)
                old.update(playbook_version=previous, status='SUPERSEDED')
                if manual.semantic_version(previous) > manual.semantic_version(anchor['playbook_version']):
                    old['supersedes'] = anchor['playbook_version']
                    anchor['status'] = 'SUPERSEDED'
                    anchor['playbook_sha256'] = independent_hash(anchor, 'playbook_sha256')
                    manifest['playbooks'].append(anchor)
                old['playbook_sha256'] = independent_hash(old, 'playbook_sha256')
                current.update(playbook_version=successor, supersedes=previous)
                current['playbook_sha256'] = independent_hash(current, 'playbook_sha256')
                manifest['playbooks'].append(old)
                manifest['current_versions'][current['playbook_id']] = successor
                self.write(manual.MANIFEST, manifest)
                if allowed:
                    with self.reviewed_fixture_anchors(manifest):
                        self.assertEqual(manual.load_playbook(current['playbook_id'], self.root)[1]['playbook_version'], successor)
                else:
                    with self.assertRaises(manual.ContractError):
                        manual.load_playbook(current['playbook_id'], self.root)
        self.write(manual.MANIFEST, original)

    def test_expiry_normal_aware_clock_spellings_preserve_reuse(self):
        original = manual.load_catalog(self.root)
        for expiry in ('2099-01-01T00:00:00Z', '2099-01-01T00:00:00+00:00',
                       '2099-01-01T09:00:00+09:00', '2099-01-01T00:00:00-04:00',
                       '2099-01-01T00:00:00.123456Z', '2099-01-01 00:00:00+00:00',
                       '2099-01-01T00:00:00+23:59', None):
            with self.subTest(expiry=expiry):
                catalog = copy.deepcopy(original)
                next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')['expiry'] = expiry
                self.write(manual.CATALOG, catalog)
                packet, scope = self.packet()
                packet['reuse_entries'] = ['group_591']
                self.assertEqual(self.validate(self.bind(packet), scope)['status'], 'VALIDATED_PREPARE_ONLY')
        self.write(manual.CATALOG, original)

    def test_malformed_expiry_offsets_refuse_reuse_and_rebound_packet(self):
        original = manual.load_catalog(self.root)
        for expiry in ('2099-01-01T00:00:00+00:60', '2099-01-01T00:00:00+01:99',
                       '2099-01-01T00:00:00+99:00', '2099-01-01T00:00:00+24:00',
                       '2099-01-01T00:00:00', '2099-01-01',
                       '2099-01-01T00:00:00+00/00', '2099-01-01X00:00:00Z'):
            with self.subTest(expiry=expiry):
                catalog = copy.deepcopy(original)
                next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')['expiry'] = expiry
                self.write(manual.CATALOG, catalog)
                with self.assertRaisesRegex(manual.ContractError, 'catalog_expiry_invalid'):
                    manual.lookup_reuse('group_591', self.root)
                packet, scope = self.packet()
                packet['reuse_entries'] = ['group_591']
                self.rejected(self.bind(packet), scope, 'catalog_expiry_invalid')
        self.write(manual.CATALOG, original)

    def test_cli_malformed_expiry_returns_two_without_invoking_worker(self):
        for name in ('mission_contract.py', 'r1000_config.py'):
            shutil.copyfile(ROOT / name, self.root / name)
        original = manual.load_catalog(self.root)
        for expiry in ('2099-01-01T00:00:00+00:60', '2099-01-01T00:00:00+01:99'):
            with self.subTest(expiry=expiry):
                catalog = copy.deepcopy(original)
                next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')['expiry'] = expiry
                self.write(manual.CATALOG, catalog)
                packet, scope = self.packet()
                packet['reuse_entries'] = ['group_591']
                self.write('packet.json', self.bind(packet))
                self.write('scope.json', scope)
                result = subprocess.run([sys.executable, str(self.root / 'tools/manual_foundation.py'),
                    '--packet', str(self.root / 'packet.json'), '--scope', str(self.root / 'scope.json'),
                    '--expected-base', BASE], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                output = json.loads(result.stdout)
                self.assertEqual(output['reason'], 'catalog_expiry_invalid')
                self.assertFalse(output['worker_invoked'])
        self.write(manual.CATALOG, original)

    def test_fixed_operating_contracts_cannot_be_dropped_by_manifest_rebinding(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        contracts = ('AGENTS.md', 'docs/RUN287_GITHUB_AGENT_OPERATING_STANDARD.md',
                     'docs/AGENT_SHARED_LESSONS_LEDGER.md', 'docs/MANUAL_FOUNDATION_V1.md')
        for key in manual.PLAYBOOK_IDS:
            for name in contracts:
                with self.subTest(playbook=key, omitted=name):
                    self.write(manual.MANIFEST, original)
                    packet, scope = self.packet(key)
                    manifest = copy.deepcopy(original)
                    manifest['policy_refs'] = [p for p in manifest['policy_refs'] if p != name]
                    self.write(manual.MANIFEST, manifest)
                    self.assertIn(name, manual.required_dependencies(key, self.root))
                    packet['dependencies'].pop(name, None)
                    scope['dependencies'].pop(name, None)
                    self.rejected(self.rebind_dependency(packet, scope, manual.MANIFEST), scope,
                                  'missing_dependency')
        self.write(manual.MANIFEST, original)

    def test_every_operating_contract_byte_change_invalidates_all_playbook_packets(self):
        for key in manual.PLAYBOOK_IDS:
            for name in ('AGENTS.md', 'docs/RUN287_GITHUB_AGENT_OPERATING_STANDARD.md',
                         'docs/AGENT_SHARED_LESSONS_LEDGER.md', 'docs/MANUAL_FOUNDATION_V1.md'):
                with self.subTest(playbook=key, changed=name):
                    original = (self.root / name).read_bytes()
                    packet, scope = self.packet(key)
                    (self.root / name).write_bytes(original + b'\n# updated contract fixture\n')
                    try:
                        self.rejected(packet, scope, 'dependency_bytes_changed')
                        self.assertEqual(self.validate(self.rebind_dependency(packet, scope, name), scope)
                                         ['status'], 'VALIDATED_PREPARE_ONLY')
                    finally:
                        (self.root / name).write_bytes(original)

    def succession_packet(self, previous, successor, supersedes, *, older=None):
        packet, scope = self.packet()
        manifest = manual.board.read_json(self.root / manual.MANIFEST)
        current = manifest['playbooks'][0]
        anchor = copy.deepcopy(current)
        old = copy.deepcopy(current)
        old.update(playbook_version=previous, status='SUPERSEDED')
        if manual.semantic_version(previous) > manual.semantic_version(anchor['playbook_version']):
            old['supersedes'] = anchor['playbook_version']
            if older != anchor['playbook_version']:
                anchor['status'] = 'SUPERSEDED'
                anchor['playbook_sha256'] = independent_hash(anchor, 'playbook_sha256')
                manifest['playbooks'].append(anchor)
        old['playbook_sha256'] = independent_hash(old, 'playbook_sha256')
        current.update(playbook_version=successor, supersedes=supersedes)
        current['playbook_sha256'] = independent_hash(current, 'playbook_sha256')
        manifest['playbooks'].append(old)
        if older:
            earlier = copy.deepcopy(old)
            earlier.update(playbook_version=older, supersedes=None)
            earlier['playbook_sha256'] = independent_hash(earlier, 'playbook_sha256')
            manifest['playbooks'].append(earlier)
        manifest['current_versions'][current['playbook_id']] = successor
        self.write(manual.MANIFEST, manifest)
        packet.update(playbook_version=successor, playbook_sha256=current['playbook_sha256'])
        return self.rebind_dependency(packet, scope, manual.MANIFEST), scope

    def test_null_predecessor_cannot_bypass_history_after_full_rebinding(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for successor in ('0.9.0', '1.1.0'):
            with self.subTest(successor=successor):
                self.write(manual.MANIFEST, original)
                packet, scope = self.succession_packet('1.0.0', successor, None)
                self.rejected(packet, scope, 'missing_playbook_predecessor')
        self.write(manual.MANIFEST, original)

    def test_current_version_cannot_skip_a_higher_history_row(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for successor, reason in (('1.1.0', 'playbook_version_not_increasing'),
                                  ('1.3.0', 'playbook_predecessor_not_latest')):
            with self.subTest(successor=successor):
                self.write(manual.MANIFEST, original)
                packet, scope = self.succession_packet('1.2.0', successor, '1.0.0', older='1.0.0')
                self.rejected(packet, scope, reason)
        self.write(manual.MANIFEST, original)

    def test_normal_upgrade_with_explicit_latest_predecessor_validates_packet(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for previous, successor in (('1.0.0', '1.1.0'), ('1.9.0', '1.10.0'),
                                    ('1.0.9', '1.0.10')):
            with self.subTest(previous=previous, successor=successor):
                self.write(manual.MANIFEST, original)
                packet, scope = self.succession_packet(previous, successor, previous)
                with self.reviewed_fixture_anchors(manual.board.read_json(self.root / manual.MANIFEST)):
                    self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
        self.write(manual.MANIFEST, original)

    def test_empty_reuse_selection_still_refuses_rebound_invalid_catalog(self):
        original = manual.load_catalog(self.root)
        for case, reason in (('expired', 'catalog_reuse_expired'),
                             ('head', 'catalog_pr_head_identity'),
                             ('successor', 'catalog_supersedes_invariant'),
                             ('hash', 'catalog_unpinned_reuse_path')):
            with self.subTest(case=case):
                self.write(manual.CATALOG, original)
                packet, scope = self.packet()
                self.assertEqual(packet['reuse_entries'], [])
                catalog = copy.deepcopy(original)
                row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_591')
                if case == 'expired':
                    row['expiry'] = '2000-01-01T00:00:00Z'
                elif case == 'head':
                    row['source_heads']['#591'] = 'invalid-head'
                elif case == 'successor':
                    row['superseded_by'] = 'group_423_574'
                else:
                    row['dependency_hashes'].clear()
                self.write(manual.CATALOG, catalog)
                self.rejected(self.rebind_dependency(packet, scope, manual.CATALOG), scope, reason)
        self.write(manual.CATALOG, original)

    def test_empty_reuse_selection_with_valid_catalog_remains_prepare_only(self):
        packet, scope = self.packet()
        self.assertEqual(packet['reuse_entries'], [])
        result = self.validate(packet, scope)
        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
        self.assertFalse(result['worker_invoked'])

    def test_empty_toolbox_refuses_all_fully_rebound_playbooks(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for key in manual.PLAYBOOK_IDS:
            with self.subTest(playbook=key):
                self.write(manual.MANIFEST, original)
                packet, scope = self.packet(key)
                manifest = copy.deepcopy(original)
                row = next(r for r in manifest['playbooks'] if r['playbook_id'] == key)
                row['toolbox_refs'] = []
                row['playbook_sha256'] = independent_hash(row, 'playbook_sha256')
                self.write(manual.MANIFEST, manifest)
                packet.update(toolbox_refs=[], playbook_sha256=row['playbook_sha256'])
                # Reproduce the old dependency builder after Toolbox removal.
                shared = set(manifest['policy_refs']) | {
                    manual.MANIFEST, manual.SCHEMA, manual.CATALOG, manual.DNR,
                    'docs/AGENT_SHARED_LESSONS_LEDGER.md', 'tools/manual_foundation.py',
                    'tools/run_agent_board.py', 'tools/check_run287_do_not_repeat.py',
                    'research/control_plane/agent_contracts_v2.yaml',
                    'research/control_plane/task_packet_schema.json'}
                packet['dependencies'] = {p: h for p, h in packet['dependencies'].items() if p in shared}
                scope['dependencies'] = copy.deepcopy(packet['dependencies'])
                self.rejected(self.rebind_dependency(packet, scope, manual.MANIFEST), scope,
                              'manual_layers_missing')
        self.write(manual.MANIFEST, original)

    def test_a1_canonical_toolbox_still_binds_reader_and_source_contract(self):
        packet, scope = self.packet('A1_SOURCE_ADMISSION_REFRESH')
        for path in ('tools/research_data_access.py', 'docs/RESEARCH_DATA_ACCESS.md'):
            self.assertIn(path, packet['toolbox_refs'])
            self.assertIn(path, packet['dependencies'])
        self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')

    def test_invalid_canonical_coverage_threshold_cannot_allow_unchanged_candidate(self):
        original = manual.board.read_json(self.root / manual.DNR)
        row = next(r for r in original['entries'] if r['id'] == 'broad_gross_floor')
        for threshold in (float('nan'), float('inf'), float('-inf'), -1.0, True, None,
                          '-inf', 'NaN', 'Infinity', '-1e309', 'invalid', '', '5.0'):
            with self.subTest(threshold=threshold):
                self.write(manual.DNR, original)
                packet, scope = self.packet()
                packet['do_not_repeat_candidate'] = {k: row[k] for k in ('signal', 'mechanism', 'book', 'window')}
                registry = copy.deepcopy(original)
                registry['reuse_policy']['minimum_component_coverage_increase_pp'] = threshold
                self.write(manual.DNR, registry)
                self.rejected(self.rebind_dependency(packet, scope, manual.DNR), scope)
        for spelling in ('-1e309', '1e309'):
            with self.subTest(raw_numeric_token=spelling):
                self.write(manual.DNR, original)
                packet, scope = self.packet()
                packet['do_not_repeat_candidate'] = {k: row[k] for k in ('signal', 'mechanism', 'book', 'window')}
                raw = json.dumps(original).replace('"minimum_component_coverage_increase_pp": 5.0',
                    '"minimum_component_coverage_increase_pp": ' + spelling)
                (self.root / manual.DNR).write_text(raw)
                self.rejected(self.rebind_dependency(packet, scope, manual.DNR), scope)
        self.write(manual.DNR, original)

    def test_finite_nonnegative_coverage_thresholds_keep_canonical_exceptions(self):
        original = manual.board.read_json(self.root / manual.DNR)
        row = next(r for r in original['entries'] if r['id'] == 'broad_gross_floor')
        candidate = {k: row[k] for k in ('signal', 'mechanism', 'book', 'window')}
        for threshold in (0, 0.0, 5, 5.0, 7.5):
            with self.subTest(threshold=threshold):
                registry = copy.deepcopy(original)
                registry['reuse_policy']['minimum_component_coverage_increase_pp'] = threshold
                self.write(manual.DNR, registry)
                for exception in (dict(component_coverage_increase_pp=threshold),
                                  dict(semantics_changed=True, change_note='Changed application semantics')):
                    packet, scope = self.packet()
                    packet['do_not_repeat_candidate'] = {**candidate, **exception}
                    self.assertEqual(self.validate(self.bind(packet), scope)['status'], 'VALIDATED_PREPARE_ONLY')
                if threshold > 0:
                    packet, scope = self.packet()
                    packet['do_not_repeat_candidate'] = candidate.copy()
                    self.rejected(self.bind(packet), scope, 'BLOCKED_DO_NOT_REPEAT')
        self.write(manual.DNR, original)

    def test_canonical_match_fields_refuse_fully_rebound_registry_changes(self):
        original = manual.board.read_json(self.root / manual.DNR)
        fields = ['signal', 'mechanism', 'book', 'window']
        row = next(r for r in original['entries'] if r['id'] == 'broad_gross_floor')
        variants = {'missing': None, 'null': None, 'empty': [], 'extra': fields + ['id'],
                    'omitted': fields[:-1], 'reordered': list(reversed(fields)),
                    'duplicate': fields + ['signal'], 'string': ','.join(fields),
                    'mapping': {k: True for k in fields}}
        for case, value in variants.items():
            with self.subTest(case=case):
                self.write(manual.DNR, original)
                packet, scope = self.packet()
                packet['do_not_repeat_candidate'] = {k: row[k] for k in fields}
                registry = copy.deepcopy(original)
                if case == 'missing':
                    del registry['match_fields']
                else:
                    registry['match_fields'] = value
                self.write(manual.DNR, registry)
                self.rejected(self.rebind_dependency(packet, scope, manual.DNR), scope,
                              'do_not_repeat_match_fields_not_canonical')
        self.write(manual.DNR, original)

    def test_canonical_match_fields_preserve_block_and_allowed_controls(self):
        registry = manual.board.read_json(self.root / manual.DNR)
        fields = ['signal', 'mechanism', 'book', 'window']
        self.assertEqual(registry['match_fields'], fields)
        row = next(r for r in registry['entries'] if r['id'] == 'broad_gross_floor')
        candidate = {k: row[k] for k in fields}
        packet, scope = self.packet()
        packet['do_not_repeat_candidate'] = candidate.copy()
        self.rejected(self.bind(packet), scope, 'BLOCKED_DO_NOT_REPEAT')
        for change in (dict(component_coverage_increase_pp=5.0),
                       dict(semantics_changed=True, change_note='Different application semantics'),
                       dict(window='SYNTHETIC_NEW_WINDOW')):
            with self.subTest(change=change):
                packet, scope = self.packet()
                packet['do_not_repeat_candidate'] = {**candidate, **change}
                result = self.validate(self.bind(packet), scope)
                self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                self.assertFalse(result['completed_task'])

    def test_current_stop_conditions_refuse_fully_rebound_manifest_changes(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        variants = {'missing': None, 'null': None, 'empty': [],
                    'string': 'CALLER_ONLY_STOP', 'mapping': {'stop': True}, 'boolean': True}
        for changed_key in manual.PLAYBOOK_IDS:
            for requested_key in manual.PLAYBOOK_IDS:
                for case, value in variants.items():
                    with self.subTest(changed=changed_key, requested=requested_key, case=case):
                        self.write(manual.MANIFEST, original)
                        packet, scope = self.packet(requested_key)
                        manifest = copy.deepcopy(original)
                        row = next(r for r in manifest['playbooks'] if r['playbook_id'] == changed_key)
                        if case == 'missing':
                            del row['process']['stop_condition']
                        else:
                            row['process']['stop_condition'] = value
                        row['playbook_sha256'] = independent_hash(row, 'playbook_sha256')
                        self.write(manual.MANIFEST, manifest)
                        if changed_key == requested_key:
                            packet['playbook_sha256'] = row['playbook_sha256']
                        packet['stop_condition'] = ['CALLER_ONLY_STOP']
                        self.rejected(self.rebind_dependency(packet, scope, manual.MANIFEST), scope,
                                      'manual_stop_condition_invalid')
        self.write(manual.MANIFEST, original)

    def test_nonempty_current_stop_conditions_keep_required_stops(self):
        for key in manual.PLAYBOOK_IDS:
            with self.subTest(playbook=key):
                _, row = manual.load_playbook(key, self.root)
                self.assertIsInstance(row['process']['stop_condition'], list)
                self.assertTrue(row['process']['stop_condition'])
                packet, scope = self.packet(key)
                packet['stop_condition'].append('ADDITIONAL_TASK_STOP')
                result = self.validate(self.bind(packet), scope)
                self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                self.assertFalse(result['worker_invoked'])
                packet['stop_condition'].remove(row['process']['stop_condition'][0])
                self.rejected(self.bind(packet), scope, 'manual_contract_changed')

    def rebind_all(self, packet, scope, manifest=None):
        if manifest is not None:
            for row in manifest['playbooks']:
                row['playbook_sha256'] = independent_hash(row, 'playbook_sha256')
            self.write(manual.MANIFEST, manifest)
            row = next(row for row in manifest['playbooks']
                       if row['playbook_id'] == packet['playbook_id'] and row['status'] == 'CURRENT')
            packet.update(playbook_version=row['playbook_version'],
                          playbook_sha256=row['playbook_sha256'], toolbox_refs=row['toolbox_refs'].copy())
        for name in packet['dependencies']:
            packet['dependencies'][name] = scope['dependencies'][name] = hashlib.sha256(
                (self.root / name).read_bytes()).hexdigest()
        return self.bind(packet)

    def test_dnr_normalized_identity_refuses_blank_missing_and_wrong_types(self):
        fields = ('signal', 'mechanism', 'book', 'window')
        for field in fields:
            for value in ('', ' ', '\t\r\n', ' \u00a0\u2003\t ', None, False, 0, [], {}):
                with self.subTest(field=field, value=value):
                    packet, scope = self.packet()
                    candidate = dict.fromkeys(fields, 'VALID_NEW_IDENTITY')
                    candidate[field] = value
                    packet['do_not_repeat_candidate'] = candidate
                    self.rejected(self.rebind_all(packet, scope), scope)
            packet, scope = self.packet()
            packet['do_not_repeat_candidate'] = dict.fromkeys(fields, 'VALID_NEW_IDENTITY')
            del packet['do_not_repeat_candidate'][field]
            self.rejected(self.rebind_all(packet, scope), scope)
        packet, scope = self.packet()
        packet['do_not_repeat_candidate'] = dict.fromkeys(fields, ' \t\u2003\n')
        self.rejected(self.rebind_all(packet, scope), scope, 'do_not_repeat_identity_invalid')

    def test_dnr_normalized_valid_identities_preserve_blocks_and_exceptions(self):
        registry = manual.board.read_json(self.root / manual.DNR)
        row = next(row for row in registry['entries'] if row.get('blocked_reuse'))
        candidate = {field: ' \t' + row[field].upper() + '\u2003 '
                     for field in ('signal', 'mechanism', 'book', 'window')}
        packet, scope = self.packet()
        packet['do_not_repeat_candidate'] = copy.deepcopy(candidate)
        self.rejected(self.rebind_all(packet, scope), scope, 'BLOCKED_DO_NOT_REPEAT')
        for exception in ({'component_coverage_increase_pp': 5.0},
                          {'semantics_changed': True, 'change_note': 'Actual changed application'},
                          {'signal': ' VALID_NEW_COMBINATION '}):
            packet, scope = self.packet()
            packet['do_not_repeat_candidate'] = dict(candidate, **exception)
            result = self.validate(self.rebind_all(packet, scope), scope)
            self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
            self.assertFalse(result['economic_authority'])

    def test_reviewed_version_anchor_has_exact_existing_blob_provenance(self):
        # Canonical manifest bytes remain unchanged in this correction. This
        # binds the code anchor to the independently retrieved reviewed blob.
        raw = (ROOT / manual.MANIFEST).read_bytes()
        git_blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        self.assertEqual(git_blob, manual.VERSION_ANCHOR_BLOB)
        self.assertEqual(manual.VERSION_ANCHOR_HEAD, '86bdcd474ae12d240d1dac31f72f758f45f26843')
        baseline = json.loads(raw)
        self.assertEqual(dict(manual.VERSION_ANCHOR), baseline['current_versions'])
        self.assertEqual(set(manual.VERSION_ANCHOR),
                         {(row['playbook_id'], row['playbook_version']) for row in baseline['playbooks']})
        for row in baseline['playbooks']:
            semantic = {k: v for k, v in row.items() if k != 'status'}
            self.assertEqual(manual.VERSION_ANCHOR_CONTENT[(row['playbook_id'], row['playbook_version'])],
                             independent_hash(semantic, 'playbook_sha256'))

    def test_history_removal_cannot_reset_reviewed_anchor_after_all_hash_rebinding(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            for selected in manual.PLAYBOOK_IDS:
                for version in ('0.0.0', '0.9.0', '1.1.0'):
                    with self.subTest(changed=changed, selected=selected, version=version):
                        self.write(manual.MANIFEST, original)
                        packet, scope = self.packet(selected)
                        manifest = copy.deepcopy(original)
                        manifest['playbooks'] = [row for row in manifest['playbooks'] if row['status'] == 'CURRENT']
                        row = next(row for row in manifest['playbooks'] if row['playbook_id'] == changed)
                        row.update(playbook_version=version, supersedes=None)
                        manifest['current_versions'][changed] = version
                        # Attacker-controlled declarations are not the anchor.
                        manifest['version_anchor'] = {changed: version}
                        self.rejected(self.rebind_all(packet, scope, manifest), scope,
                                      'missing_reviewed_playbook_anchor')
        self.write(manual.MANIFEST, original)

    def test_reviewed_anchor_preserves_full_upgrade_lineage_for_all_playbooks(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            self.write(manual.MANIFEST, original)
            packet, scope = self.packet(changed)
            manifest = copy.deepcopy(original)
            current = next(row for row in manifest['playbooks'] if row['playbook_id'] == changed)
            anchor = copy.deepcopy(current)
            anchor['status'] = 'SUPERSEDED'
            middle = copy.deepcopy(anchor)
            middle.update(playbook_version='1.1.0', supersedes='1.0.0')
            current.update(playbook_version='1.2.0', supersedes='1.1.0')
            manifest['current_versions'][changed] = '1.2.0'
            manifest['playbooks'].extend([anchor, middle])
            with self.reviewed_fixture_anchors(manifest, {(changed, '1.1.0')}):
                result = self.validate(self.rebind_all(packet, scope, manifest), scope, propose_successor=True)
            self.assertEqual(result['playbook_version'], '1.2.0')
            self.assertFalse(result['completed_task'])
        self.write(manual.MANIFEST, original)

    def test_historical_predecessor_edge_cannot_be_erased_after_full_rebinding(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            self.write(manual.MANIFEST, original)
            packet, scope = self.packet()
            manifest = copy.deepcopy(original)
            current = next(row for row in manifest['playbooks'] if row['playbook_id'] == changed)
            anchor = copy.deepcopy(current)
            anchor['status'] = 'SUPERSEDED'
            middle = copy.deepcopy(anchor)
            middle.update(playbook_version='1.1.0', supersedes=None)
            current.update(playbook_version='1.2.0', supersedes='1.1.0')
            manifest['current_versions'][changed] = '1.2.0'
            manifest['playbooks'].extend([anchor, middle])
            self.rejected(self.rebind_all(packet, scope, manifest), scope,
                          'reviewed_playbook_lineage_invalid')
        self.write(manual.MANIFEST, original)

    def test_a1_reader_closure_remains_required_when_toolbox_refs_are_removed(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        expected = {'tools/research_data_access.py', 'data_static/research_dataset_registry_v1.json',
                    'tools/long_history_lake.py', 'tools/macro_history_sources.py',
                    'tools/macro_research_checkpoint.py', 'tools/run_data_freshness_contract.py',
                    'r1000_legacy_input_guard.py'}
        packet, scope = self.packet('A1_SOURCE_ADMISSION_REFRESH')
        manifest = copy.deepcopy(original)
        row = next(row for row in manifest['playbooks'] if row['playbook_id'] == packet['playbook_id'])
        old = copy.deepcopy(row)
        old['status'] = 'SUPERSEDED'
        manifest['playbooks'].append(old)
        row.update(playbook_version='1.1.0', supersedes='1.0.0')
        manifest['current_versions'][row['playbook_id']] = '1.1.0'
        row['toolbox_refs'] = ['docs/RESEARCH_DATA_ACCESS.md']
        self.rebind_all(packet, scope, manifest)
        with self.reviewed_fixture_anchors(manifest):
            self.assertTrue(expected.issubset(manual.required_dependencies(packet['playbook_id'], self.root)))
            self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
            for name in expected:
                with self.subTest(name=name):
                    altered, altered_scope = copy.deepcopy(packet), copy.deepcopy(scope)
                    del altered['dependencies'][name]
                    del altered_scope['dependencies'][name]
                    self.rejected(self.rebind_all(altered, altered_scope), altered_scope, 'missing_dependency')
        self.write(manual.MANIFEST, original)

    def test_each_reader_dependency_byte_change_invalidates_existing_a1_packet(self):
        packet, scope = self.packet('A1_SOURCE_ADMISSION_REFRESH')
        for name in manual.A1_READER_DEPENDENCIES:
            with self.subTest(name=name):
                target = self.root / name
                raw = target.read_bytes()
                try:
                    target.write_bytes(raw + b'\n ')
                    self.rejected(packet, scope, 'dependency_bytes_changed:' + name)
                finally:
                    target.write_bytes(raw)
        self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')

    def test_all_current_nested_instructions_refuse_fully_rebound_mutations(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            for selected in manual.PLAYBOOK_IDS:
                for layer, field in (('process', 'steps'), ('process', 'stop_condition'),
                                     ('proof', 'checks'), ('learning', 'steps')):
                    for case, value in (('missing', None), ('null', None), ('empty', []),
                                        ('string', 'instruction'), ('mapping', {'step': 'instruction'}),
                                        ('boolean', False), ('blank', [' \t\u2003\n']),
                                        ('blank_member', ['valid', ' \u00a0\t']), ('nonstring_member', ['valid', 1])):
                        with self.subTest(changed=changed, selected=selected, layer=layer, field=field, case=case):
                            self.write(manual.MANIFEST, original)
                            packet, scope = self.packet(selected)
                            manifest = copy.deepcopy(original)
                            row = next(row for row in manifest['playbooks'] if row['playbook_id'] == changed)
                            if case == 'missing':
                                del row[layer][field]
                            else:
                                row[layer][field] = value
                            reason = ('manual_stop_condition_invalid' if field == 'stop_condition'
                                      else 'manual_instructions_invalid:' + layer + '.' + field)
                            if case == 'missing' and layer == 'proof':
                                reason = 'manual_layers_missing'
                            self.rejected(self.rebind_all(packet, scope, manifest), scope, reason)
        self.write(manual.MANIFEST, original)

    def test_valid_nested_instructions_and_additional_caller_stop_remain_prepare_only(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for key in manual.PLAYBOOK_IDS:
            self.write(manual.MANIFEST, original)
            packet, scope = self.packet(key)
            manifest = copy.deepcopy(original)
            row = next(row for row in manifest['playbooks'] if row['playbook_id'] == key)
            old = copy.deepcopy(row)
            old['status'] = 'SUPERSEDED'
            manifest['playbooks'].append(old)
            row.update(playbook_version='1.1.0', supersedes='1.0.0')
            manifest['current_versions'][key] = '1.1.0'
            for layer, field in (('process', 'steps'), ('proof', 'checks'), ('learning', 'steps')):
                row[layer][field].append('Additional meaningful instruction')
            packet['stop_condition'].append('ADDITIONAL_CALLER_STOP')
            with self.reviewed_fixture_anchors(manifest):
                result = self.validate(self.rebind_all(packet, scope, manifest), scope)
            self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
            self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
            self.assertFalse(result['worker_invoked'])
            self.assertFalse(result['economic_authority'])
        self.write(manual.MANIFEST, original)

    def test_reviewed_semantic_content_cannot_change_at_same_version_after_full_rebinding(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            for selected in manual.PLAYBOOK_IDS:
                for layer, field in (('process', 'steps'), ('process', 'stop_condition'),
                                     ('proof', 'checks'), ('learning', 'steps')):
                    with self.subTest(changed=changed, selected=selected, layer=layer, field=field):
                        self.write(manual.MANIFEST, original)
                        packet, scope = self.packet(selected)
                        manifest = copy.deepcopy(original)
                        row = next(r for r in manifest['playbooks'] if r['playbook_id'] == changed)
                        row[layer][field] = ['Meaningful changed content without advancing the version']
                        if selected == changed and field == 'stop_condition':
                            packet['stop_condition'] = row[layer][field].copy()
                        self.rejected(self.rebind_all(packet, scope, manifest), scope,
                                      'reviewed_playbook_content_changed')
        self.write(manual.MANIFEST, original)

    def test_reviewed_anchor_covers_other_semantics_and_unknown_content_fields(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            for field in ('trigger', 'inputs', 'proof_set', 'extra_content'):
                with self.subTest(changed=changed, field=field):
                    self.write(manual.MANIFEST, original)
                    packet, scope = self.packet()
                    manifest = copy.deepcopy(original)
                    row = next(r for r in manifest['playbooks'] if r['playbook_id'] == changed)
                    if field in ('trigger', 'inputs'):
                        row['process'][field] = 'Changed trigger' if field == 'trigger' else ['Changed input']
                    else:
                        row[field] = ['Meaningfully changed content']
                    self.rejected(self.rebind_all(packet, scope, manifest), scope,
                                  'reviewed_playbook_content_changed')
        self.write(manual.MANIFEST, original)

    def test_changed_semantics_require_upgrade_and_immutable_retained_predecessor(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            for selected in manual.PLAYBOOK_IDS:
                with self.subTest(changed=changed, selected=selected):
                    self.write(manual.MANIFEST, original)
                    packet, scope = self.packet(selected)
                    manifest = copy.deepcopy(original)
                    row = next(r for r in manifest['playbooks'] if r['playbook_id'] == changed)
                    old = copy.deepcopy(row)
                    old['status'] = 'SUPERSEDED'
                    row.update(playbook_version='1.1.0', supersedes='1.0.0')
                    row['process']['steps'].append('Changed instructions in the new version')
                    manifest['playbooks'].append(old)
                    manifest['current_versions'][changed] = '1.1.0'
                    with self.reviewed_fixture_anchors(manifest):
                        result = self.validate(self.rebind_all(packet, scope, manifest), scope)
                    self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                    self.assertFalse(result['economic_authority'])
                    old['proof']['checks'].append('Retrospectively changed reviewed content')
                    self.rejected(self.rebind_all(packet, scope, manifest), scope,
                                  'reviewed_playbook_content_changed')
        self.write(manual.MANIFEST, original)

    def test_unselected_catalog_failure_references_fail_closed_with_full_rebinding(self):
        original = manual.board.read_json(self.root / manual.CATALOG)
        for selected in manual.PLAYBOOK_IDS:
            for case, refs in (('missing', None), ('null', None), ('empty', []),
                               ('unknown', ['UNKNOWN_REF']), ('mixed', ['broad_gross_floor', 'UNKNOWN_REF']),
                               ('blank', [' \t\n']), ('nonstring', [None]), ('string', 'broad_gross_floor'),
                               ('duplicate', ['broad_gross_floor', 'broad_gross_floor'])):
                with self.subTest(selected=selected, case=case):
                    self.write(manual.CATALOG, original)
                    packet, scope = self.packet(selected)
                    catalog = copy.deepcopy(original)
                    row = next(r for r in catalog['entries'] if r['classification'] == 'DO_NOT_REPEAT')
                    if case == 'missing':
                        del row['do_not_repeat_refs']
                    else:
                        row['do_not_repeat_refs'] = refs
                    self.write(manual.CATALOG, catalog)
                    self.assertEqual(packet['reuse_entries'], [])
                    self.assertNotIn('do_not_repeat_candidate', packet)
                    self.rejected(self.rebind_all(packet, scope), scope, 'do_not_repeat_')
        self.write(manual.CATALOG, original)

    def test_all_catalog_reference_classes_are_validated_and_canonical_refs_remain_valid(self):
        original = manual.board.read_json(self.root / manual.CATALOG)
        for classification in ('REUSE_NOW', 'SELECTIVE_PORT', 'HISTORICAL_LESSON'):
            self.write(manual.CATALOG, original)
            packet, scope = self.packet()
            catalog = copy.deepcopy(original)
            row = next(r for r in catalog['entries'] if r['classification'] == classification)
            row['do_not_repeat_refs'] = ['UNKNOWN_REF']
            self.write(manual.CATALOG, catalog)
            self.rejected(self.rebind_all(packet, scope), scope, 'do_not_repeat_ref_missing')
        self.write(manual.CATALOG, original)
        packet, scope = self.packet()
        self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
        self.assertEqual(manual.lookup_reuse('group_174', self.root)['blocked_registry_ids'],
                         ['broad_gross_floor'])

    def test_invalid_registry_entries_cannot_bypass_canonical_validation_or_evaluator(self):
        original = manual.board.read_json(self.root / manual.DNR)
        fields = ('signal', 'mechanism', 'book', 'window')
        mutations = ('blocked_false', 'blocked_integer', 'blocked_missing', 'missing_id',
                     'invalid_id', 'duplicate_id', 'duplicate_normalized_id', 'duplicate_descriptor',
                     'empty_entries', 'nonobject_entry', 'missing_status') + tuple('blank_' + f for f in fields)
        for selected in manual.PLAYBOOK_IDS:
            for mutation in mutations:
                with self.subTest(selected=selected, mutation=mutation):
                    self.write(manual.DNR, original)
                    packet, scope = self.packet(selected)
                    registry = copy.deepcopy(original)
                    row = registry['entries'][0]
                    packet['do_not_repeat_candidate'] = {f: row[f] for f in fields}
                    if mutation == 'blocked_false':
                        row['blocked_reuse'] = False
                    elif mutation == 'blocked_integer':
                        row['blocked_reuse'] = 1
                    elif mutation == 'blocked_missing':
                        del row['blocked_reuse']
                    elif mutation == 'missing_id':
                        del row['id']
                    elif mutation == 'invalid_id':
                        row['id'] = 'invalid id!'
                    elif mutation == 'duplicate_id':
                        registry['entries'][1]['id'] = row['id']
                    elif mutation == 'duplicate_normalized_id':
                        duplicate = copy.deepcopy(row)
                        duplicate['id'] = row['id'] + '_'
                        duplicate['signal'] = 'A distinct otherwise valid signal'
                        registry['entries'].append(duplicate)
                    elif mutation == 'duplicate_descriptor':
                        for f in fields:
                            registry['entries'][1][f] = ' \t' + row[f].upper() + ' '
                    elif mutation == 'empty_entries':
                        registry['entries'] = []
                    elif mutation == 'nonobject_entry':
                        registry['entries'][0] = None
                    elif mutation == 'missing_status':
                        del row['status']
                    else:
                        row[mutation[6:]] = ' \t\n'
                    with self.assertRaises(ValueError):
                        manual.validated_do_not_repeat_entries(registry)
                    self.write(manual.DNR, registry)
                    with patch.object(manual, 'evaluate_candidate', side_effect=AssertionError('must not evaluate invalid registry')):
                        self.rejected(self.rebind_all(packet, scope), scope, 'do_not_repeat_registry_invalid')
        self.write(manual.DNR, original)

    def test_registry_is_validated_without_candidate_and_validator_dependency_is_mandatory(self):
        original = manual.board.read_json(self.root / manual.DNR)
        dependency = 'tools/build_run287_u0_v2_github_census.py'
        for key in manual.PLAYBOOK_IDS:
            self.write(manual.DNR, original)
            packet, scope = self.packet(key)
            registry = copy.deepcopy(original)
            registry['entries'][0]['blocked_reuse'] = False
            self.write(manual.DNR, registry)
            self.rejected(self.rebind_all(packet, scope), scope, 'do_not_repeat_registry_invalid')
            self.write(manual.DNR, original)
            packet, scope = self.packet(key)
            del packet['dependencies'][dependency]
            del scope['dependencies'][dependency]
            self.rejected(self.bind(packet), scope, 'missing_dependency')
            packet, scope = self.packet(key)
            raw = (self.root / dependency).read_bytes()
            try:
                (self.root / dependency).write_bytes(raw + b'\n# changed validator fixture\n')
                self.rejected(packet, scope, 'dependency_bytes_changed:' + dependency)
            finally:
                (self.root / dependency).write_bytes(raw)

    def test_registry_descriptors_and_ids_cannot_be_coerced_from_nontext_json(self):
        original = manual.board.read_json(self.root / manual.DNR)
        for key in manual.PLAYBOOK_IDS:
            for field in ('id', 'status', 'signal', 'mechanism', 'book', 'window'):
                for value in (1, True, ['valid'], {'identity': 'valid'}):
                    with self.subTest(key=key, field=field, value=value):
                        self.write(manual.DNR, original)
                        packet, scope = self.packet(key)
                        registry = copy.deepcopy(original)
                        registry['entries'][0][field] = value
                        self.write(manual.DNR, registry)
                        self.rejected(self.rebind_all(packet, scope), scope, 'do_not_repeat_registry_invalid')
        self.write(manual.DNR, original)

    def test_coverage_overflow_is_refused_before_evaluation_and_finite_controls_remain_valid(self):
        row = manual.board.read_json(self.root / manual.DNR)['entries'][0]
        blocked = {f: row[f] for f in ('signal', 'mechanism', 'book', 'window')}
        for key in manual.PLAYBOOK_IDS:
            for coverage in (10**309, -(10**309), 10**399, -(10**399)):
                packet, scope = self.packet(key)
                packet['do_not_repeat_candidate'] = dict(blocked, component_coverage_increase_pp=coverage)
                with patch.object(manual, 'evaluate_candidate', side_effect=AssertionError('must not convert overflow')):
                    self.rejected(self.rebind_all(packet, scope), scope, 'do_not_repeat_coverage_invalid')
            for candidate in (dict(blocked, component_coverage_increase_pp=5),
                              dict(blocked, component_coverage_increase_pp=10**308),
                              dict(blocked, component_coverage_increase_pp=sys.float_info.max),
                              dict(blocked, component_coverage_increase_pp=-1, semantics_changed=True,
                                   change_note='Approved semantic change fixture'),
                              dict(blocked, signal='VALID_NEW_SIGNAL', component_coverage_increase_pp=0)):
                packet, scope = self.packet(key)
                packet['do_not_repeat_candidate'] = candidate
                result = self.validate(self.rebind_all(packet, scope), scope)
                self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                self.assertFalse(result['economic_authority'])

    def test_cli_overflow_returns_blocked_input_and_children_preserve_optimization(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONOPTIMIZE=str(sys.flags.optimize))
        env['PYTHONPATH'] = str(ROOT) + os.pathsep + env.get('PYTHONPATH', '')
        prefix = [sys.executable, '-B'] + (['-O'] if sys.flags.optimize else [])
        child = subprocess.run(prefix + ['-c', 'import sys; print(sys.flags.optimize)'],
                               env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(int(child.stdout), sys.flags.optimize)
        row = manual.board.read_json(self.root / manual.DNR)['entries'][0]
        blocked = {f: row[f] for f in ('signal', 'mechanism', 'book', 'window')}
        for key in manual.PLAYBOOK_IDS:
            for coverage in (10**399, -(10**399)):
                with self.subTest(key=key, sign=coverage > 0):
                    packet, scope = self.packet(key)
                    packet['do_not_repeat_candidate'] = dict(blocked, component_coverage_increase_pp=coverage)
                    self.rebind_all(packet, scope)
                    self.write('packet.json', packet)
                    self.write('scope.json', scope)
                    command = prefix + [str(self.root / 'tools/manual_foundation.py'), '--packet',
                                        str(self.root / 'packet.json'), '--scope', str(self.root / 'scope.json'),
                                        '--expected-base', BASE, '--expected-review-head', REVIEW_HEAD]
                    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(json.loads(result.stdout), {'status': 'BLOCKED_INPUT',
                                     'reason': 'do_not_repeat_coverage_invalid', 'worker_invoked': False})
                    self.assertNotIn('Traceback', result.stderr)

    def test_every_reviewed_successor_content_is_immutable_even_when_unselected(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            for version in ('1.1.0', '1.2.0'):
                manifest = copy.deepcopy(original)
                row = self.successor_fixture(manifest, changed, '1.1.0')
                if version == '1.2.0':
                    row = self.successor_fixture(manifest, changed, version)
                row['process']['steps'].append('Separately reviewed successor fixture')
                for selected in manual.PLAYBOOK_IDS:
                    self.write(manual.MANIFEST, original)
                    packet, scope = self.packet(selected)
                    reviewed = self.reviewed_fixture_anchors(manifest)
                    with reviewed:
                        self.assertEqual(self.validate(self.rebind_all(packet, scope, manifest), scope)['status'],
                                         'VALIDATED_PREPARE_ONLY')
                        for layer, field in (('process', 'steps'), ('process', 'stop_condition'),
                                             ('proof', 'checks'), ('learning', 'steps')):
                            with self.subTest(changed=changed, selected=selected, version=version, field=field):
                                altered = copy.deepcopy(manifest)
                                target = next(r for r in altered['playbooks']
                                              if r['playbook_id'] == changed and r['status'] == 'CURRENT')
                                target[layer][field] = ['Changed same-version content after independent review']
                                candidate, verified_scope = copy.deepcopy(packet), copy.deepcopy(scope)
                                current = next(r for r in altered['playbooks']
                                               if r['playbook_id'] == selected and r['status'] == 'CURRENT')
                                candidate['stop_condition'] = current['process']['stop_condition'].copy()
                                self.rejected(self.rebind_all(candidate, verified_scope, altered), verified_scope,
                                              'reviewed_playbook_content_changed', propose_successor=True)
        self.write(manual.MANIFEST, original)

    def test_later_reviewed_retained_versions_cannot_change_or_disappear(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for changed in manual.PLAYBOOK_IDS:
            manifest = copy.deepcopy(original)
            self.successor_fixture(manifest, changed, '1.1.0')
            self.successor_fixture(manifest, changed, '1.2.0')
            reviewed = self.reviewed_fixture_anchors(manifest, {(changed, '1.1.0')})
            self.write(manual.MANIFEST, original)
            packet, scope = self.packet(changed)
            with reviewed:
                baseline = self.rebind_all(packet, scope, manifest)
                self.assertEqual(self.validate(baseline, scope, propose_successor=True)['status'],
                                 'VALIDATED_SUCCESSOR_PROPOSAL_ONLY')
                for layer, field in (('process', 'steps'), ('process', 'stop_condition'),
                                     ('proof', 'checks'), ('learning', 'steps')):
                    altered = copy.deepcopy(manifest)
                    old = next(r for r in altered['playbooks']
                               if r['playbook_id'] == changed and r['playbook_version'] == '1.1.0')
                    old[layer][field].append('Retrospective alteration of an accepted predecessor')
                    p, s = copy.deepcopy(packet), copy.deepcopy(scope)
                    self.rejected(self.rebind_all(p, s, altered), s, 'reviewed_playbook_content_changed',
                                  propose_successor=True)
                altered = copy.deepcopy(manifest)
                altered['playbooks'] = [r for r in altered['playbooks']
                                       if (r['playbook_id'], r['playbook_version']) != (changed, '1.1.0')]
                next(r for r in altered['playbooks'] if r['playbook_id'] == changed
                     and r['status'] == 'CURRENT')['supersedes'] = '1.0.0'
                p, s = copy.deepcopy(packet), copy.deepcopy(scope)
                self.rejected(self.rebind_all(p, s, altered), s, 'missing_reviewed_playbook_anchor',
                              propose_successor=True)
        self.write(manual.MANIFEST, original)

    def test_successor_proposals_require_reviewed_anchors_for_adoption_and_retention(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for key in manual.PLAYBOOK_IDS:
            self.write(manual.MANIFEST, original)
            packet, scope = self.packet(key)
            manifest = copy.deepcopy(original)
            self.successor_fixture(manifest, key, '1.1.0')
            self.rebind_all(packet, scope, manifest)
            self.rejected(packet, scope, 'unreviewed_playbook_version')
            result = self.validate(packet, scope, propose_successor=True)
            self.assertEqual(result['status'], 'VALIDATED_SUCCESSOR_PROPOSAL_ONLY')
            self.assertEqual(result['proposed_playbook_versions'], {key: '1.1.0'})
            self.assertTrue(result['adoption_requires_independent_anchor_review'])
            self.assertFalse(result['worker_invoked'])
            self.assertFalse(result['completed_task'])
            self.assertFalse(result['economic_authority'])
            self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
            # Caller-controlled manifest claims cannot become the trusted table.
            manifest['version_anchor_content'] = {key: {'1.1.0': packet['playbook_sha256']}}
            self.rejected(self.rebind_all(packet, scope, manifest), scope, 'unreviewed_playbook_version')
            with self.reviewed_fixture_anchors(manifest):
                adopted = self.validate(packet, scope)
                self.assertEqual(adopted['status'], 'VALIDATED_PREPARE_ONLY')
                self.assertNotIn('proposed_playbook_versions', adopted)
            self.successor_fixture(manifest, key, '1.2.0')
            self.rejected(self.rebind_all(packet, scope, manifest), scope,
                          'unreviewed_retained_playbook_version', propose_successor=True)
        self.write(manual.MANIFEST, original)

    def test_manifest_and_catalog_nonobject_roots_fail_closed_after_full_hash_rebinding(self):
        for name, reason, loader in ((manual.MANIFEST, 'manual_manifest_invalid',
                                     lambda: manual.load_playbook('L0_RESUME_HANDOFF', self.root)),
                                    (manual.CATALOG, 'catalog_contract', lambda: manual.load_catalog(self.root))):
            original = (self.root / name).read_bytes()
            for selected in manual.PLAYBOOK_IDS:
                for root in ([], None, 42, 6.25, 'nonobject', True, False):
                    with self.subTest(name=name, selected=selected, root=root):
                        packet, scope = self.packet(selected)
                        try:
                            self.write(name, root)
                            with self.assertRaisesRegex(manual.ContractError, reason):
                                loader()
                            self.rejected(self.rebind_all(packet, scope), scope, reason)
                        finally:
                            (self.root / name).write_bytes(original)

    def test_real_cli_nonobject_canonical_roots_return_structured_blocked_input(self):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONOPTIMIZE=str(sys.flags.optimize))
        prefix = [sys.executable, '-B'] + (['-O'] if sys.flags.optimize else [])
        child = subprocess.run(prefix + ['-c', 'import sys; print(sys.flags.optimize)'],
                               env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(int(child.stdout), sys.flags.optimize)
        for name, reason in ((manual.MANIFEST, 'manual_manifest_invalid'), (manual.CATALOG, 'catalog_contract')):
            original = (self.root / name).read_bytes()
            for root in ([], None, 42, 6.25, 'nonobject', True, False):
                with self.subTest(name=name, root=root):
                    packet, scope = self.packet()
                    try:
                        self.write(name, root)
                        self.rebind_all(packet, scope)
                        result = self.cli_fixture(packet, scope)
                        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                        self.assertEqual(json.loads(result.stdout), {'status': 'BLOCKED_INPUT',
                                         'reason': reason, 'worker_invoked': False})
                        self.assertNotIn('Traceback', result.stderr)
                        self.assertNotIn('AttributeError', result.stderr)
                    finally:
                        (self.root / name).write_bytes(original)
        packet, scope = self.packet()
        result = self.cli_fixture(packet, scope)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'VALIDATED_PREPARE_ONLY')

    def test_real_cli_successor_proposal_is_not_automatic_adoption(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for key in manual.PLAYBOOK_IDS:
            self.write(manual.MANIFEST, original)
            packet, scope = self.packet(key)
            manifest = copy.deepcopy(original)
            self.successor_fixture(manifest, key, '1.1.0')
            self.rebind_all(packet, scope, manifest)
            blocked = self.cli_fixture(packet, scope)
            self.assertEqual(blocked.returncode, 2, blocked.stdout + blocked.stderr)
            self.assertEqual(json.loads(blocked.stdout)['reason'], 'unreviewed_playbook_version')
            proposal = self.cli_fixture(packet, scope, propose_successor=True)
            self.assertEqual(proposal.returncode, 0, proposal.stdout + proposal.stderr)
            result = json.loads(proposal.stdout)
            self.assertEqual(result['status'], 'VALIDATED_SUCCESSOR_PROPOSAL_ONLY')
            self.assertTrue(result['adoption_requires_independent_anchor_review'])
            self.assertFalse(result['worker_invoked'])
            self.assertFalse(result['economic_authority'])
        self.write(manual.MANIFEST, original)

    def test_l0_mandatory_board_closure_cannot_be_removed_from_proposed_toolbox(self):
        expected = {'mission_contract.py', 'r1000_config.py', 'requirements_github.txt',
                    'research/control_plane/system_state_schema.json', 'tools/materialize_system_state.py'}
        packet, scope = self.packet()
        manifest = manual.board.read_json(self.root / manual.MANIFEST)
        current = self.successor_fixture(manifest, packet['playbook_id'], '1.1.0')
        current['toolbox_refs'] = ['docs/MANUAL_FOUNDATION_V1.md']
        self.rebind_all(packet, scope, manifest)
        self.assertTrue(expected.issubset(manual.required_dependencies(packet['playbook_id'], self.root,
                                                                     propose_successor=True)))
        self.assertEqual(self.validate(packet, scope, propose_successor=True)['status'],
                         'VALIDATED_SUCCESSOR_PROPOSAL_ONLY')
        for name in expected:
            with self.subTest(name=name):
                p, s = copy.deepcopy(packet), copy.deepcopy(scope)
                del p['dependencies'][name]
                del s['dependencies'][name]
                self.rejected(self.rebind_all(p, s), s, 'missing_dependency', propose_successor=True)

    def test_l0_old_packet_byte_pins_and_independent_scope_survive_packet_rehash(self):
        for name in ('mission_contract.py', 'r1000_config.py', 'requirements_github.txt',
                     'research/control_plane/system_state_schema.json', 'tools/materialize_system_state.py'):
            with self.subTest(name=name):
                packet, scope = self.packet()
                original = (self.root / name).read_bytes()
                try:
                    (self.root / name).write_bytes(original + b'\n')
                    self.rejected(self.bind(packet), scope, 'dependency_bytes_changed:' + name)
                    result = self.cli_fixture(packet, scope)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(json.loads(result.stdout)['reason'], 'dependency_bytes_changed:' + name)
                    self.assertNotIn('Traceback', result.stderr)
                    fresh_packet, fresh_scope = copy.deepcopy(packet), copy.deepcopy(scope)
                    self.rebind_dependency(fresh_packet, fresh_scope, name)
                    self.assertEqual(self.validate(fresh_packet, fresh_scope)['status'], 'VALIDATED_PREPARE_ONLY')
                    self.rejected(fresh_packet, scope, 'wrong_dependency')
                    del fresh_packet['dependencies'][name]
                    del fresh_scope['dependencies'][name]
                    self.rejected(self.bind(fresh_packet), fresh_scope, 'missing_dependency')
                finally:
                    (self.root / name).write_bytes(original)

    def test_unselected_successor_is_refused_after_complete_hash_rebinding(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for selected in manual.PLAYBOOK_IDS:
            for other in manual.PLAYBOOK_IDS:
                if other == selected:
                    continue
                for attack in ('valid_toolbox', 'missing_toolbox', 'changed_reader'):
                    with self.subTest(selected=selected, other=other, attack=attack):
                        self.write(manual.MANIFEST, original)
                        packet, scope = self.packet(selected)
                        manifest = copy.deepcopy(original)
                        row = self.successor_fixture(manifest, other, '1.1.0')
                        reader = self.root / 'tools/research_data_access.py'
                        reader_bytes = reader.read_bytes()
                        try:
                            if attack == 'missing_toolbox':
                                row['toolbox_refs'].append('tools/nonexistent_unselected_successor_toolbox.py')
                            if attack == 'changed_reader':
                                reader.write_bytes(reader_bytes + b'\n# changed unselected Reader\n')
                            self.rebind_all(packet, scope, manifest)
                            self.rejected(packet, scope, 'unreviewed_playbook_version')
                            self.rejected(packet, scope, 'unselected_unreviewed_playbook_version',
                                          propose_successor=True)
                            with self.assertRaisesRegex(manual.ContractError,
                                                       'unselected_unreviewed_playbook_version'):
                                manual.required_dependencies(selected, self.root, propose_successor=True)
                        finally:
                            reader.write_bytes(reader_bytes)
        self.write(manual.MANIFEST, original)

    def test_real_cli_unselected_successor_refuses_without_traceback(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for selected in manual.PLAYBOOK_IDS:
            for other in manual.PLAYBOOK_IDS:
                if other == selected:
                    continue
                self.write(manual.MANIFEST, original)
                packet, scope = self.packet(selected)
                manifest = copy.deepcopy(original)
                row = self.successor_fixture(manifest, other, '1.1.0')
                row['toolbox_refs'].append('tools/nonexistent_unselected_successor_toolbox.py')
                self.rebind_all(packet, scope, manifest)
                child = self.cli_fixture(packet, scope, propose_successor=True)
                self.assertEqual(child.returncode, 2, child.stdout + child.stderr)
                self.assertEqual(json.loads(child.stdout), dict(status='BLOCKED_INPUT',
                    reason='unselected_unreviewed_playbook_version', worker_invoked=False))
                self.assertEqual(child.stderr, '')
        self.write(manual.MANIFEST, original)

    def test_proposal_receipt_reports_only_selected_with_trusted_other_successor(self):
        original = manual.board.read_json(self.root / manual.MANIFEST)
        for selected in manual.PLAYBOOK_IDS:
            for other in manual.PLAYBOOK_IDS:
                if other == selected:
                    continue
                self.write(manual.MANIFEST, original)
                packet, scope = self.packet(selected)
                manifest = copy.deepcopy(original)
                self.successor_fixture(manifest, other, '1.1.0')
                self.successor_fixture(manifest, selected, '1.1.0')
                # Establish the synthetic reviewed OTHER anchor before validation;
                # it is fixture context, never production approval or adoption.
                with self.reviewed_fixture_anchors(manifest, {(other, '1.1.0')}):
                    self.rebind_all(packet, scope, manifest)
                    result = self.validate(packet, scope, propose_successor=True)
                    self.assertEqual(result['proposed_playbook_versions'], {selected: '1.1.0'})
                    self.assertFalse(result['completed_task'])
                    self.assertFalse(result['worker_invoked'])
                    self.assertTrue(result['adoption_requires_independent_anchor_review'])
                    self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
        self.write(manual.MANIFEST, original)

    def test_a6_requires_actual_registered_programs_and_combined_imports(self):
        # Oracle is the existing runner's actual registry, not the implementation
        # inventory being tested. No runner main/proof procedure is invoked.
        programs = {path for path, _ in registered_validation.DEFAULT_TESTS}
        programs.update({'tests/control_plane_agent_contract_smoke.py',
                         'tests/system_state_materializer_smoke.py',
                         'tests/manual_foundation_smoke.py', 'tools/run_pr_validation.py'})
        self.assertEqual(len(registered_validation.DEFAULT_TESTS), 236)
        self.assertEqual(registered_validation.DEFAULT_TESTS.count(
            ('tests/alpaca_sip_managed_refresh_smoke.py', [])), 1)
        required = set(manual.required_dependencies('A6_INDEPENDENT_QA', self.root))
        self.assertTrue(programs.issubset(required), sorted(programs - required))
        for name in ('tests/alpaca_sip_managed_refresh_smoke.py',
                     'tools/alpaca_sip_managed_refresh.py',
                     'tools/prepare_a1_managed_ohlcv.py'):
            self.assertEqual(manual.A6_FIXED_PROOF_PROGRAMS.count(name), 1)
            self.assertIn(name, required)
            self.assertTrue((self.root / name).is_file(), name)
        self.assertTrue({'tools/materialize_system_state.py', 'mission_contract.py',
                         'tools/run_orchestrator.py',
                         'tools/research_data_access.py', 'tests/frozen_stage_ab_fairness_smoke.py',
                         'tools/frozen_stage_ab_fairness.py',
                         'tests/twelve_data_credential_preflight_smoke.py',
                         'tests/twelve_private_capture_smoke.py',
                         'tools/twelve_private_capture.py',
                         '.github/workflows/twelve_private_capture.yml',
                         '.github/workflows/api_credentials_check.yml',
                         '.github/workflows/twelve_data_credential_preflight.yml'}.issubset(required))
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        result = self.validate(packet, scope)
        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
        self.assertFalse(result['worker_invoked'])
        self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})

    def test_a6_managed_refresh_closure_refuses_changed_and_rebound_missing_pins(self):
        # Independent literal witnesses: the registered program plus the local
        # managed/prepare imports it consumes. No proof/collector is invoked.
        names = ('tests/alpaca_sip_managed_refresh_smoke.py',
                 'tools/alpaca_sip_managed_refresh.py',
                 'tools/prepare_a1_managed_ohlcv.py')
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        for name in names:
            with self.subTest(path=name):
                self.assertIn(name, packet['dependencies'])
                target = self.root / name
                original = target.read_bytes()
                self.assertEqual(original, fixture_dependency_bytes(name, 'HEAD'))
                try:
                    target.write_bytes(original + b'\n# synthetic changed managed proof\n')
                    self.rejected(packet, scope, 'dependency_bytes_changed:' + name)
                finally:
                    target.write_bytes(original)
                omitted, verified = copy.deepcopy(packet), copy.deepcopy(scope)
                del omitted['dependencies'][name]
                del verified['dependencies'][name]
                self.rebind_all(omitted, verified)
                self.rejected(omitted, verified, 'missing_dependency')
        result = self.validate(packet, scope)
        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
        self.assertFalse(result['worker_invoked'])
        self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})

    def test_a6_canonical_contract_reads_refuse_stale_and_rebound_omissions(self):
        # Literal witnesses from registered tests and their actual default reads,
        # independent of the validator inventory. Never run economic programs.
        names = (
            'tools/run_orchestrator.py',
            'data_static/run287_durable_environment_contract.json',
            'data_static/run287_promotion_gate_contract.json',
            'docs/run287_chameleon_macro_risk_contract.json',
            'docs/run287_expected_return_challenger_contract.json',
            'docs/run287_expected_return_v2_contract.json',
            'docs/run287_next_scheduled_artifact_gate_contract.json',
            'docs/run287_ohlcv_pattern_memory_contract.json',
            'docs/nav_metrics_v3_rf_optional_contract.json',
            'docs/run287_same_close_target_contract.json',
            'docs/run287_sec_management_guidance_scout_contract.json',
            'docs/run287_sector_leadership_challenger_contract.json',
            'docs/run287_u0_v3_acceptance_contract.json',
            'docs/run287_u0_v3_recovery_contract.json',
        )
        controls = {path: (self.root / path).read_bytes()
                    for path in (manual.MANIFEST, manual.CATALOG)}
        for name in names:
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            original = (ROOT / name).read_bytes()
            target.write_bytes(original)
            with self.subTest(path=name):
                try:
                    packet, scope = self.packet('A6_INDEPENDENT_QA')
                    packet['stop_condition'].append('SYNTHETIC_CALLER_STOP')
                    self.bind(packet)
                    target.write_bytes(original + b'\n')
                    self.rejected(packet, scope, 'dependency_bytes_changed:' + name)
                    child = self.cli_fixture(packet, scope)
                    self.assertEqual(child.returncode, 2, child.stdout + child.stderr)
                    self.assertEqual(json.loads(child.stdout)['reason'],
                                     'dependency_bytes_changed:' + name)
                    self.assertEqual(child.stderr, '')

                    # Fresh complete pins permit preparation, never completed proof.
                    fresh, fresh_scope = self.packet('A6_INDEPENDENT_QA')
                    fresh['stop_condition'].append('SYNTHETIC_CALLER_STOP')
                    self.rebind_schema_fixture(fresh, fresh_scope)
                    child = self.cli_fixture(fresh, fresh_scope)
                    self.assertEqual(child.returncode, 0, child.stdout + child.stderr)
                    self.assertEqual(child.stderr, '')
                    for result in (self.validate(fresh, fresh_scope), json.loads(child.stdout)):
                        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                        self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                        self.assertFalse(result['worker_invoked'])
                        self.assertFalse(result['completed_task'])
                        self.assertFalse(result['economic_authority'])

                    # Rebind manifest, catalog, dependencies, packet and scope.
                    del fresh['dependencies'][name]
                    del fresh_scope['dependencies'][name]
                    self.rebind_schema_fixture(fresh, fresh_scope)
                    self.rejected(fresh, fresh_scope, 'missing_dependency')
                    for removed in (False, True):
                        if removed:
                            target.unlink()
                        child = self.cli_fixture(fresh, fresh_scope)
                        self.assertEqual(child.returncode, 2, child.stdout + child.stderr)
                        self.assertEqual(json.loads(child.stdout)['reason'], 'missing_dependency')
                        self.assertEqual(child.stderr, '')
                finally:
                    target.write_bytes(original)
                    for path, raw in controls.items():
                        (self.root / path).write_bytes(raw)

    def test_a6_proof_inputs_refuse_stale_bytes_and_rebound_omissions(self):
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        contracts = {name: (self.root / name).read_bytes()
                     for name in (manual.MANIFEST, manual.CATALOG)}
        for name in manual.A6_FIXED_PROOF_INPUTS:
            with self.subTest(path=name):
                original = (self.root / name).read_bytes()
                try:
                    self.assertIn(name, packet['dependencies'])
                    (self.root / name).write_bytes(original + b'\n')
                    self.rejected(packet, scope, 'dependency_bytes_changed:' + name)
                    p, s = copy.deepcopy(packet), copy.deepcopy(scope)
                    del p['dependencies'][name]
                    del s['dependencies'][name]
                    self.rejected(self.rebind_schema_fixture(p, s), s, 'missing_dependency')
                finally:
                    (self.root / name).write_bytes(original)
                    for path, raw in contracts.items():
                        (self.root / path).write_bytes(raw)

    def test_a6_actual_workflow_and_contract_consumers_have_cli_pin_controls(self):
        # Independent examples from actual registered readers, not the product
        # inventory: account-window, workflow-glob, Reader, census and public UI.
        for name in ('.github/workflows/full_rebuild_manual.yml',
                     '.github/workflows/review_complete_gate.yml',
                     'data_static/research_dataset_registry_v1.json',
                     'docs/research_dataset_generation_v1.schema.json',
                     'docs/run287_p0_3_authority_census/workflow_registry.yaml',
                     'docs/public/app.js',
                     'research/sec_13f_cusip_map_overrides.csv',
                     'manifests/fullrun/run287_canonical_a_20260731.json'):
            with self.subTest(path=name):
                original = (self.root / name).read_bytes()
                contracts = {path: (self.root / path).read_bytes()
                             for path in (manual.MANIFEST, manual.CATALOG)}
                try:
                    packet, scope = self.packet('A6_INDEPENDENT_QA')
                    self.assertIn(name, packet['dependencies'])
                    (self.root / name).write_bytes(original + b'\n')
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertEqual(json.loads(cli.stdout)['reason'],
                                     'dependency_bytes_changed:' + name)
                    self.assertEqual(cli.stderr, '')
                    fresh, fresh_scope = self.packet('A6_INDEPENDENT_QA')
                    self.rebind_schema_fixture(fresh, fresh_scope)
                    result = self.validate(fresh, fresh_scope)
                    self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                    self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                    cli = self.cli_fixture(fresh, fresh_scope)
                    self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
                    self.assertEqual(cli.stderr, '')
                    del fresh['dependencies'][name]
                    del fresh_scope['dependencies'][name]
                    self.rebind_schema_fixture(fresh, fresh_scope)
                    cli = self.cli_fixture(fresh, fresh_scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertEqual(json.loads(cli.stdout)['reason'], 'missing_dependency')
                    self.assertEqual(cli.stderr, '')
                finally:
                    (self.root / name).write_bytes(original)
                    for path, raw in contracts.items():
                        (self.root / path).write_bytes(raw)

    def test_a6_new_workflow_glob_input_requires_a_fresh_pin(self):
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        name = '.github/workflows/SYNTHETIC_PROOF_INPUT.yml'
        (self.root / name).write_text('name: synthetic offline fixture\njobs: {}\n')
        for rebound in (False, True):
            with self.subTest(rebound=rebound):
                if rebound:
                    self.rebind_schema_fixture(packet, scope)
                self.rejected(packet, scope, 'missing_dependency')
                cli = self.cli_fixture(packet, scope)
                self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                self.assertEqual(json.loads(cli.stdout)['reason'], 'missing_dependency')
                self.assertEqual(cli.stderr, '')
        packet['dependencies'][name] = scope['dependencies'][name] = hashlib.sha256(
            (self.root / name).read_bytes()).hexdigest()
        self.rebind_schema_fixture(packet, scope)
        self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
        cli = self.cli_fixture(packet, scope)
        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
        self.assertEqual(set(json.loads(cli.stdout)['proof_results'].values()), {'NOT_RUN'})
        self.assertEqual(cli.stderr, '')

        (self.root / name).unlink()
        (self.root / name).mkdir()
        self.rejected(packet, scope, 'a6_proof_input_not_file')
        cli = self.cli_fixture(packet, scope)
        self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
        self.assertEqual(json.loads(cli.stdout)['reason'], 'a6_proof_input_not_file')
        self.assertEqual(cli.stderr, '')
        (self.root / name).rmdir()
        (self.root / name).symlink_to(self.root / 'docs/public/app.js')
        self.rejected(packet, scope, 'symlink_path')
        cli = self.cli_fixture(packet, scope)
        self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
        self.assertEqual(json.loads(cli.stdout)['reason'], 'symlink_path')
        self.assertEqual(cli.stderr, '')

    def test_catalog_future_verification_refuses_all_rows_after_full_rebinding(self):
        original = manual.load_catalog(self.root)
        contracts = {name: (self.root / name).read_bytes()
                     for name in (manual.MANIFEST, manual.CATALOG)}
        for reuse in ([], ['group_158']):
            packet, scope = self.packet()
            packet['reuse_entries'] = reuse
            for index, row in enumerate(original['entries']):
                for clock in ('2099-01-01T00:00:00Z',
                              '2099-01-01T09:00:00+09:00',
                              '2098-12-31T20:00:00-04:00'):
                    with self.subTest(reuse=reuse, entry=row['entry_id'], clock=clock):
                        try:
                            catalog = copy.deepcopy(original)
                            catalog['entries'][index]['verified_at'] = clock
                            self.write(manual.CATALOG, catalog)
                            with self.assertRaisesRegex(manual.ContractError,
                                                        'catalog_verified_at_future'):
                                manual.load_catalog(self.root)
                            p, s = copy.deepcopy(packet), copy.deepcopy(scope)
                            self.rejected(self.rebind_schema_fixture(p, s), s,
                                          'catalog_verified_at_future')
                        finally:
                            for name, raw in contracts.items():
                                (self.root / name).write_bytes(raw)
        for selected in manual.PLAYBOOK_IDS:
            for reuse in ([], ['group_158']):
                try:
                    packet, scope = self.packet(selected)
                    packet['reuse_entries'] = reuse
                    catalog = copy.deepcopy(original)
                    next(row for row in catalog['entries']
                         if row['entry_id'] == 'group_158')['verified_at'] = '2099-01-01T00:00:00Z'
                    self.write(manual.CATALOG, catalog)
                    self.rebind_schema_fixture(packet, scope)
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertEqual(json.loads(cli.stdout)['reason'], 'catalog_verified_at_future')
                    self.assertEqual(cli.stderr, '')
                finally:
                    for name, raw in contracts.items():
                        (self.root / name).write_bytes(raw)

    def test_catalog_now_past_and_future_expiry_controls_preserve_reuse(self):
        from datetime import datetime, timedelta, timezone
        frozen = datetime.now(timezone.utc)
        original = manual.load_catalog(self.root)
        with patch.object(manual, 'datetime') as clock:
            clock.now.return_value = frozen
            for verified in (frozen, frozen - timedelta(microseconds=1),
                             frozen.astimezone(timezone(timedelta(hours=9)))):
                catalog = copy.deepcopy(original)
                row = next(row for row in catalog['entries'] if row['entry_id'] == 'group_158')
                row['verified_at'] = verified.isoformat()
                row['expiry'] = '2030-01-01T00:00:00Z'
                self.write(manual.CATALOG, catalog)
                packet, scope = self.packet()
                packet['reuse_entries'] = ['group_158']
                self.rebind_schema_fixture(packet, scope)
                self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
                self.assertTrue(manual.lookup_reuse('group_158', self.root)['allowed'])
            row['verified_at'] = (frozen + timedelta(microseconds=1)).isoformat()
            self.write(manual.CATALOG, catalog)
            with self.assertRaisesRegex(manual.ContractError, 'catalog_verified_at_future'):
                manual.lookup_reuse('group_158', self.root)

    def test_reconciled_a6_proof_inputs_refuse_stale_or_missing_pins(self):
        for name in ('tests/twelve_data_credential_preflight_smoke.py',
                     'tests/twelve_private_capture_smoke.py',
                     'tools/twelve_private_capture.py',
                     '.github/workflows/twelve_private_capture.yml',
                     '.github/workflows/api_credentials_check.yml',
                     '.github/workflows/twelve_data_credential_preflight.yml'):
            with self.subTest(path=name):
                original = (self.root / name).read_bytes()
                try:
                    packet, scope = self.packet('A6_INDEPENDENT_QA')
                    self.assertIn(name, packet['dependencies'])
                    (self.root / name).write_bytes(original + b'\n# SYNTHETIC PROOF CHANGE\n')
                    self.rejected(packet, scope, 'dependency_bytes_changed')
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertEqual(json.loads(cli.stdout)['status'], 'BLOCKED_INPUT')
                    self.assertEqual(cli.stderr, '')
                    packet, scope = self.packet('A6_INDEPENDENT_QA')
                    result = self.validate(packet, scope)
                    self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                    self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
                    self.assertEqual(json.loads(cli.stdout)['status'], 'VALIDATED_PREPARE_ONLY')
                    self.assertEqual(cli.stderr, '')
                    del packet['dependencies'][name]
                    del scope['dependencies'][name]
                    self.rejected(self.rebind_schema_fixture(packet, scope), scope, 'missing_dependency')
                    cli = self.cli_fixture(packet, scope)
                    self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                    self.assertEqual(json.loads(cli.stdout)['reason'], 'missing_dependency')
                    self.assertEqual(cli.stderr, '')
                finally:
                    (self.root / name).write_bytes(original)

    def test_a6_node_child_runtime_refuses_stale_and_rebound_missing_pins(self):
        # Literal witnesses include a subprocess program and an asset consumed
        # by inline Node; neither appears in a Python import/read inventory.
        for name in ('tests/public_dashboard_runtime_smoke.js',
                     'docs/public/project-results.js',
                     'data_static/run287_promotion_state.json'):
            with self.subTest(name=name):
                target = self.root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                original = (ROOT / name).read_bytes()
                target.write_bytes(original)
                packet, scope = self.packet('A6_INDEPENDENT_QA')
                self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')
                target.write_bytes(b"console.log('synthetic fixture: dashboard assertions removed');\n"
                                   if name.endswith('.js') else original + b'\n')
                self.rejected(packet, scope, 'dependency_bytes_changed')
                cli = self.cli_fixture(packet, scope)
                self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                self.assertTrue(json.loads(cli.stdout)['reason'].startswith('dependency_bytes_changed:'))
                self.assertEqual(cli.stderr, '')

                packet, scope = self.packet('A6_INDEPENDENT_QA')
                cli = self.cli_fixture(packet, scope)
                self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
                self.assertEqual(cli.stderr, '')
                for result in (self.validate(packet, scope), json.loads(cli.stdout)):
                    self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                    self.assertFalse(result['worker_invoked'])
                    self.assertFalse(result['completed_task'])
                    self.assertFalse(result['economic_authority'])
                    self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                del packet['dependencies'][name]
                del scope['dependencies'][name]
                self.rebind_schema_fixture(packet, scope)
                self.rejected(packet, scope, 'missing_dependency')
                cli = self.cli_fixture(packet, scope)
                self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                self.assertEqual(json.loads(cli.stdout)['reason'], 'missing_dependency')
                self.assertEqual(cli.stderr, '')

                target.unlink()
                self.rebind_schema_fixture(packet, scope)
                self.rejected(packet, scope, 'missing_dependency')
                cli = self.cli_fixture(packet, scope)
                self.assertEqual(cli.returncode, 2, cli.stdout + cli.stderr)
                self.assertEqual(json.loads(cli.stdout)['reason'], 'missing_dependency')
                self.assertEqual(cli.stderr, '')
                target.write_bytes(original)
                packet, scope = self.packet('A6_INDEPENDENT_QA')
                self.assertEqual(self.validate(packet, scope)['status'], 'VALIDATED_PREPARE_ONLY')

    def test_each_registered_a6_program_byte_change_refuses_old_packet(self):
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        programs = {path for path, _ in registered_validation.DEFAULT_TESTS}
        programs.update({'tests/control_plane_agent_contract_smoke.py',
                         'tests/system_state_materializer_smoke.py',
                         'tests/manual_foundation_smoke.py', 'tools/run_pr_validation.py',
                         'tests/frozen_stage_ab_fairness_smoke.py', 'tools/frozen_stage_ab_fairness.py'})
        for name in sorted(programs):
            with self.subTest(name=name):
                target = self.root / name
                original = target.read_bytes()
                try:
                    target.write_bytes(original + b'\n# changed proof program\n')
                    self.rejected(self.bind(packet), scope, 'dependency_bytes_changed:' + name)
                finally:
                    target.write_bytes(original)

    def test_a6_valuation_audit_transitive_inputs_reject_stale_and_omitted_pins(self):
        cases = {
            'tests/valuation_provenance_shadow_smoke.py': 'test_actual_main_archive_subset',
            'tools/audit_valuation_provenance_shadow.py': 'test_actual_main_archive_subset',
            'tests/fixtures/valuation_provenance/main_19rows_extracted.csv': 'test_actual_main_archive_subset',
            'tests/fixtures/valuation_provenance/concentrated_4rows_extracted.csv': 'test_actual_concentrated_archive_subset',
        }
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        prefix = [sys.executable, '-B'] + (['-O'] if sys.flags.optimize else [])
        runner = ('import importlib.util,sys,unittest; '
                  's=importlib.util.spec_from_file_location("actual_valuation_proof",sys.argv[1]); '
                  'm=importlib.util.module_from_spec(s); s.loader.exec_module(m); '
                  'r=unittest.TextTestRunner().run(unittest.TestSuite([m.AuditTests(sys.argv[2])])); '
                  'sys.exit(not r.wasSuccessful())')
        for name, method in cases.items():
            with self.subTest(name=name):
                self.assertIn(name, packet['dependencies'])
                target = self.root / name
                original = target.read_bytes()
                command = prefix + ['-c', runner,
                    str(self.root / 'tests/valuation_provenance_shadow_smoke.py'), method]
                try:
                    valid = subprocess.run(command, capture_output=True, text=True, timeout=30)
                    self.assertEqual(valid.returncode, 0, valid.stdout + valid.stderr)
                    suffix = (b'\nraise RuntimeError("synthetic-unreviewed-valuation-proof")\n'
                              if name.endswith('.py') else b'SYNTHETIC_BAD_ROW\n')
                    target.write_bytes(original + suffix)
                    changed = subprocess.run(command, capture_output=True, text=True, timeout=30)
                    self.assertNotEqual(changed.returncode, 0)
                    self.rejected(packet, scope, 'dependency_bytes_changed:' + name)
                    stale = self.cli_fixture(packet, scope)
                    self.assertEqual(stale.returncode, 2, stale.stdout + stale.stderr)
                    self.assertEqual(json.loads(stale.stdout)['reason'], 'dependency_bytes_changed:' + name)
                    self.assertEqual(stale.stderr, '')
                    omitted, verified = copy.deepcopy(packet), copy.deepcopy(scope)
                    del omitted['dependencies'][name]
                    del verified['dependencies'][name]
                    self.rebind_all(omitted, verified)
                    self.rejected(omitted, verified, 'missing_dependency')
                    missing = self.cli_fixture(omitted, verified)
                    self.assertEqual(missing.returncode, 2, missing.stdout + missing.stderr)
                    self.assertEqual(json.loads(missing.stdout)['reason'], 'missing_dependency')
                    fresh, fresh_scope = self.packet('A6_INDEPENDENT_QA')
                    result = self.validate(fresh, fresh_scope)
                    self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                    self.assertFalse(result['completed_task'])
                    self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                finally:
                    target.write_bytes(original)

    def test_each_fixed_a6_program_pin_cannot_be_omitted_and_rehashed(self):
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        for name in manual.A6_FIXED_PROOF_PROGRAMS:
            with self.subTest(name=name):
                candidate, verified = copy.deepcopy(packet), copy.deepcopy(scope)
                del candidate['dependencies'][name]
                del verified['dependencies'][name]
                self.rejected(self.rebind_all(candidate, verified), verified, 'missing_dependency')

    def test_a6_weakened_checks_refuse_old_scope_but_new_scope_is_only_preparation(self):
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        for name in ('tests/agent_board_smoke.py', 'tests/manual_foundation_smoke.py',
                     'tests/control_plane_agent_contract_smoke.py',
                     'tests/system_state_materializer_smoke.py'):
            target = self.root / name
            original = target.read_bytes()
            try:
                target.write_text('def main():\n    return 0\n')
                self.rejected(self.bind(packet), scope, 'dependency_bytes_changed:' + name)
                candidate = copy.deepcopy(packet)
                candidate['dependencies'][name] = hashlib.sha256(target.read_bytes()).hexdigest()
                self.rejected(self.bind(candidate), scope, 'wrong_dependency')
                # A genuinely new independently supplied scope binds new bytes;
                # preflight still makes no claim that the changed tests passed.
                fresh, fresh_scope = self.packet('A6_INDEPENDENT_QA')
                result = self.validate(fresh, fresh_scope)
                self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                self.assertFalse(result['completed_task'])
                self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
            finally:
                target.write_bytes(original)

    def test_real_cli_a6_changed_or_omitted_program_returns_blocked_input(self):
        for name in ('tests/agent_board_smoke.py', 'tests/manual_foundation_smoke.py'):
            packet, scope = self.packet('A6_INDEPENDENT_QA')
            target = self.root / name
            original = target.read_bytes()
            try:
                target.write_text('def main():\n    return 0\n')
                self.bind(packet)
                result = self.cli_fixture(packet, scope)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)['reason'], 'dependency_bytes_changed:' + name)
                self.assertEqual(result.stderr, '')
                del packet['dependencies'][name]
                del scope['dependencies'][name]
                self.rebind_all(packet, scope)
                result = self.cli_fixture(packet, scope)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)['reason'], 'missing_dependency')
                self.assertEqual(result.stderr, '')
            finally:
                target.write_bytes(original)

    def test_a6_fixed_proof_pins_survive_successor_toolbox_replacement(self):
        packet, scope = self.packet('A6_INDEPENDENT_QA')
        manifest = manual.board.read_json(self.root / manual.MANIFEST)
        current = self.successor_fixture(manifest, packet['playbook_id'], '1.1.0')
        current['toolbox_refs'] = ['docs/MANUAL_FOUNDATION_V1.md']
        self.rebind_all(packet, scope, manifest)
        self.assertTrue(set(manual.A6_FIXED_PROOF_PROGRAMS).issubset(
            manual.required_dependencies(packet['playbook_id'], self.root, propose_successor=True)))
        result = self.validate(packet, scope, propose_successor=True)
        self.assertEqual(result['proposed_playbook_versions'], {'A6_INDEPENDENT_QA': '1.1.0'})
        for name in ('tools/run_pr_validation.py', 'tests/agent_board_smoke.py',
                     'tests/manual_foundation_smoke.py'):
            p, s = copy.deepcopy(packet), copy.deepcopy(scope)
            del p['dependencies'][name]
            del s['dependencies'][name]
            self.rejected(self.rebind_all(p, s), s, 'missing_dependency', propose_successor=True)

    def test_new_lesson_invalidates_all_three_old_packets_then_fresh_scopes_pass(self):
        name = 'docs/AGENT_SHARED_LESSONS_LEDGER.md'
        target = self.root / name
        original = target.read_bytes()
        for selected in manual.PLAYBOOK_IDS:
            target.write_bytes(original)
            packet, scope = self.packet(selected)
            try:
                target.write_bytes(original + b'\n# reusable new corrective lesson\n')
                self.rejected(self.bind(packet), scope, 'dependency_bytes_changed:' + name)
                candidate = copy.deepcopy(packet)
                candidate['dependencies'][name] = hashlib.sha256(target.read_bytes()).hexdigest()
                self.rejected(self.bind(candidate), scope, 'wrong_dependency')
                fresh, fresh_scope = self.packet(selected)
                self.assertEqual(self.validate(fresh, fresh_scope)['status'], 'VALIDATED_PREPARE_ONLY')
            finally:
                target.write_bytes(original)

    def test_all_board_consumers_refuse_removed_materializer_pin_after_full_rebinding(self):
        name = 'tools/materialize_system_state.py'
        for selected in manual.PLAYBOOK_IDS:
            with self.subTest(selected=selected):
                packet, scope = self.packet(selected)
                self.assertIn(name, packet['dependencies'])
                del packet['dependencies'][name]
                del scope['dependencies'][name]
                self.rebind_all(packet, scope)
                self.rejected(packet, scope, 'missing_dependency')
                result = self.cli_fixture(packet, scope)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(json.loads(result.stdout)['reason'], 'missing_dependency')
                self.assertEqual(result.stderr, '')

    def test_catalog_every_row_requires_verification_provenance_after_full_rebinding(self):
        original = manual.load_catalog(self.root)
        packet, scope = self.packet()
        for index, row in enumerate(original['entries']):
            for field in ('verified_at', 'last_verified_master'):
                for value in ('missing', None, 17, 'not-valid'):
                    with self.subTest(entry=row['entry_id'], field=field, value=value):
                        try:
                            catalog = copy.deepcopy(original)
                            if value == 'missing':
                                del catalog['entries'][index][field]
                            else:
                                catalog['entries'][index][field] = value
                            self.write(manual.CATALOG, catalog)
                            reason = 'catalog_' + field + '_invalid'
                            with self.assertRaisesRegex(manual.ContractError, reason):
                                manual.load_catalog(self.root)
                            p, s = copy.deepcopy(packet), copy.deepcopy(scope)
                            self.rejected(self.rebind_all(p, s), s, reason)
                        finally:
                            self.write(manual.CATALOG, original)

    def test_selected_and_unselected_catalog_clocks_and_master_types_fail_closed(self):
        original = manual.load_catalog(self.root)
        bad = {
            'verified_at': ['', ' \t\n', True, [], {}, '2026-10-09',
                '2026-10-09T12:00:00', '2026-02-30T12:00:00Z',
                '2026-10-09T24:00:00Z', '2026-10-09T12:00:00+00:60',
                '2026-10-09T12:00:00+24:00', '0001-01-01T00:00:00+23:59',
                '9999-12-31T23:59:59-23:59'],
            'last_verified_master': ['', ' \t\n', True, [], {}, 'a' * 39,
                'a' * 41, 'g' * 40, 'A' * 40, 'a' * 40 + '\n']}
        for reuse in ([], ['group_158']):
            packet, scope = self.packet()
            packet['reuse_entries'] = reuse
            index = next(i for i, r in enumerate(original['entries']) if r['entry_id'] == 'group_158')
            for field, values in bad.items():
                for value in values:
                    with self.subTest(reuse=reuse, field=field, value=value):
                        try:
                            catalog = copy.deepcopy(original)
                            catalog['entries'][index][field] = value
                            self.write(manual.CATALOG, catalog)
                            p, s = copy.deepcopy(packet), copy.deepcopy(scope)
                            self.rejected(self.rebind_all(p, s), s, 'catalog_' + field + '_invalid')
                        finally:
                            self.write(manual.CATALOG, original)

    def test_catalog_provenance_aware_clocks_and_historical_master_preserve_reuse(self):
        original = manual.load_catalog(self.root)
        for clock in ('2026-10-09T12:00:00Z', '2026-10-09T12:00:00+00:00',
                      '2026-10-09T21:00:00+09:00', '2026-10-09T08:00:00-04:00',
                      '2026-10-09T12:00:00.123456Z', '2026-10-09 12:00:00+00:00'):
            with self.subTest(clock=clock):
                try:
                    packet, scope = self.packet()
                    packet['reuse_entries'] = ['group_158']
                    catalog = copy.deepcopy(original)
                    row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_158')
                    row['verified_at'] = clock
                    self.assertRegex(row['last_verified_master'], r'^[0-9a-f]{40}$')
                    self.write(manual.CATALOG, catalog)
                    result = self.validate(self.rebind_all(packet, scope), scope)
                    self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                    self.assertTrue(manual.lookup_reuse('group_158', self.root)['allowed'])
                    self.assertFalse(result['economic_authority'])
                finally:
                    self.write(manual.CATALOG, original)

    def test_real_cli_catalog_provenance_returns_structured_refusal_and_valid_control(self):
        original = manual.load_catalog(self.root)
        for selected in (False, True):
            for field in ('verified_at', 'last_verified_master'):
                values = ['missing', None, 17, 'not-valid']
                if field == 'verified_at':
                    values += ['0001-01-01T00:00:00+23:59', '9999-12-31T23:59:59-23:59']
                for value in values:
                    with self.subTest(selected=selected, field=field, value=value):
                        try:
                            packet, scope = self.packet()
                            packet['reuse_entries'] = ['group_158'] if selected else []
                            catalog = copy.deepcopy(original)
                            row = next(r for r in catalog['entries'] if r['entry_id'] == 'group_158')
                            if value == 'missing':
                                del row[field]
                            else:
                                row[field] = value
                            self.write(manual.CATALOG, catalog)
                            self.rebind_all(packet, scope)
                            result = self.cli_fixture(packet, scope)
                            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                            self.assertEqual(json.loads(result.stdout), {'status': 'BLOCKED_INPUT',
                                'reason': 'catalog_' + field + '_invalid', 'worker_invoked': False})
                            self.assertEqual(result.stderr, '')
                        finally:
                            self.write(manual.CATALOG, original)
        packet, scope = self.packet()
        packet['reuse_entries'] = ['group_158']
        self.bind(packet)
        result = self.cli_fixture(packet, scope)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'VALIDATED_PREPARE_ONLY')

    def test_invalid_canonical_schemas_refuse_api_and_cli_after_complete_rebinding(self):
        for name, field in ((manual.SCHEMA, 'task_key'),
                            ('research/control_plane/task_packet_schema.json', 'authority'),
                            ('research/control_plane/task_packet_schema.json', 'task_key')):
            original = (self.root / name).read_bytes()
            for selected in manual.PLAYBOOK_IDS:
                with self.subTest(schema=name, field=field, selected=selected):
                    try:
                        packet, scope = self.packet(selected)
                        schema = manual.board.read_json(self.root / name)
                        schema['properties'][field]['type'] = 17
                        self.write(name, schema)
                        self.rebind_all(packet, scope)
                        self.rejected(packet, scope, 'manual_schema_contract_invalid')
                        for value, is_scope in ((packet, False), (scope, True)):
                            with self.assertRaisesRegex(manual.ContractError, 'manual_schema_contract_invalid'):
                                manual.validate_shape(value, scope=is_scope, root=self.root)
                        result = self.cli_fixture(packet, scope)
                        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                        self.assertEqual(json.loads(result.stdout), {'status': 'BLOCKED_INPUT',
                            'reason': 'manual_schema_contract_invalid', 'worker_invoked': False})
                        self.assertEqual(result.stderr, '')
                    finally:
                        (self.root / name).write_bytes(original)
        for selected in manual.PLAYBOOK_IDS:
            packet, scope = self.packet(selected)
            result = self.cli_fixture(packet, scope)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)['status'], 'VALIDATED_PREPARE_ONLY')

    def test_unresolvable_schema_references_refuse_api_cli_after_complete_rebinding(self):
        locations = ((manual.SCHEMA, ('properties', 'task_key'), False),
                     ('research/control_plane/task_packet_schema.json',
                      ('properties', 'authority'), False),
                     (manual.SCHEMA, ('$defs', 'scope', 'properties', 'owner'), True))
        references = ({'$ref': '#/$defs/MISSING_REVIEWED_DEFINITION'},
                      {'$ref': '#MISSING_REVIEWED_ANCHOR'},
                      {'$dynamicRef': '#/$defs/MISSING_REVIEWED_DEFINITION'})
        for name, keys, is_scope in locations:
            original = (self.root / name).read_bytes()
            for selected in manual.PLAYBOOK_IDS:
                for reference in references:
                    with self.subTest(schema=name, location=keys, selected=selected,
                                      reference=reference):
                        try:
                            packet, scope = self.packet(selected)
                            schema = manual.board.read_json(self.root / name)
                            node = schema
                            for key in keys[:-1]:
                                node = node[key]
                            node[keys[-1]] = copy.deepcopy(reference)
                            manual.Draft202012Validator.check_schema(schema)
                            self.write(name, schema)
                            self.rebind_all(packet, scope)
                            self.rejected(packet, scope, 'manual_schema_contract_invalid')
                            value = scope if is_scope else packet
                            with self.assertRaisesRegex(manual.ContractError,
                                                        'manual_schema_contract_invalid'):
                                manual.validate_shape(value, scope=is_scope, root=self.root)
                            result = self.cli_fixture(packet, scope)
                            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                            self.assertEqual(json.loads(result.stdout), {'status': 'BLOCKED_INPUT',
                                'reason': 'manual_schema_contract_invalid', 'worker_invoked': False})
                            self.assertEqual(result.stderr, '')
                        finally:
                            (self.root / name).write_bytes(original)

    def rebind_schema_fixture(self, packet, scope):
        manifest = manual.board.read_json(self.root / manual.MANIFEST)
        for row in manifest['playbooks']:
            row['playbook_sha256'] = independent_hash(row, 'playbook_sha256')
        self.write(manual.MANIFEST, manifest)
        catalog = manual.board.read_json(self.root / manual.CATALOG)
        for row in catalog['entries']:
            for name in row['dependency_hashes']:
                row['dependency_hashes'][name] = hashlib.sha256((self.root / name).read_bytes()).hexdigest()
        self.write(manual.CATALOG, catalog)
        return self.rebind_all(packet, scope)

    def test_cyclic_schema_references_refuse_api_cli_after_complete_rebinding(self):
        locations = ((manual.SCHEMA, ('properties', 'task_key'), False),
                     ('research/control_plane/task_packet_schema.json',
                      ('properties', 'authority'), False),
                     (manual.SCHEMA, ('$defs', 'scope', 'properties', 'owner'), True))
        for name, keys, is_scope in locations:
            original = (self.root / name).read_bytes()
            for selected in manual.PLAYBOOK_IDS:
                for kind in ('direct', 'dynamic', 'mutual'):
                    with self.subTest(schema=name, location=keys, selected=selected, kind=kind):
                        try:
                            packet, scope = self.packet(selected)
                            schema = manual.board.read_json(self.root / name)
                            pointer = '#/' + '/'.join(keys)
                            keyword = '$dynamicRef' if kind == 'dynamic' else '$ref'
                            reference = {'allOf': [{keyword: pointer}]}
                            if kind == 'mutual':
                                # Both definitions live in the manual schema after
                                # the task authority is composed into that schema.
                                manual_schema = manual.board.read_json(self.root / manual.SCHEMA)
                                manual_schema['$defs'].update({
                                    'cycleLeft': {'allOf': [{'$ref': '#/$defs/cycleRight'}]},
                                    'cycleRight': {'allOf': [{'$ref': '#/$defs/cycleLeft'}]}})
                                self.write(manual.SCHEMA, manual_schema)
                                if name == manual.SCHEMA:
                                    schema = manual_schema
                                reference = {'$ref': '#/$defs/cycleLeft'}
                            node = schema
                            for key in keys[:-1]:
                                node = node[key]
                            node[keys[-1]] = reference
                            manual.Draft202012Validator.check_schema(schema)
                            self.write(name, schema)
                            self.rebind_schema_fixture(packet, scope)
                            self.rejected(packet, scope, 'manual_schema_contract_invalid')
                            value = scope if is_scope else packet
                            with self.assertRaisesRegex(manual.ContractError,
                                                        'manual_schema_contract_invalid'):
                                manual.validate_shape(value, scope=is_scope, root=self.root)
                            result = self.cli_fixture(packet, scope)
                            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                            self.assertEqual(json.loads(result.stdout), {'status': 'BLOCKED_INPUT',
                                'reason': 'manual_schema_contract_invalid', 'worker_invoked': False})
                            self.assertEqual(result.stderr, '')
                        finally:
                            (self.root / name).write_bytes(original)
                            if name != manual.SCHEMA:
                                shutil.copyfile(ROOT / manual.SCHEMA, self.root / manual.SCHEMA)

    def test_terminating_recursive_schemas_preserve_prepare_only(self):
        original = (self.root / manual.SCHEMA).read_bytes()
        for selected in manual.PLAYBOOK_IDS:
            for keyword in ('$ref', '$dynamicRef'):
                with self.subTest(selected=selected, keyword=keyword):
                    try:
                        packet, scope = self.packet(selected)
                        schema = manual.board.read_json(self.root / manual.SCHEMA)
                        schema['$defs']['stopTree'] = {'anyOf': [
                            {'type': 'string', 'minLength': 1},
                            {'type': 'array', 'items': {keyword: '#/$defs/stopTree'}}]}
                        schema['properties']['stop_condition'] = {keyword: '#/$defs/stopTree'}
                        schema['$defs']['dependencyTree'] = {'anyOf': [
                            {'type': 'string', 'pattern': '^[a-f0-9]{64}$'},
                            {'type': 'object', 'additionalProperties':
                                {keyword: '#/$defs/dependencyTree'}}]}
                        schema['$defs']['scope']['properties']['dependencies'] = {
                            keyword: '#/$defs/dependencyTree'}
                        self.write(manual.SCHEMA, schema)
                        self.rebind_schema_fixture(packet, scope)
                        result = self.validate(packet, scope)
                        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                        for field in ('worker_invoked', 'completed_task', 'economic_authority'):
                            self.assertFalse(result[field])
                        self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                        manual.validate_shape(scope, scope=True, root=self.root)
                        cli = self.cli_fixture(packet, scope)
                        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
                        self.assertEqual(json.loads(cli.stdout)['status'], 'VALIDATED_PREPARE_ONLY')
                        self.assertEqual(cli.stderr, '')
                    finally:
                        (self.root / manual.SCHEMA).write_bytes(original)

    def test_external_schema_references_refuse_without_retrieval(self):
        original = (self.root / manual.SCHEMA).read_bytes()
        references = ('https://example.invalid/manual-contract.json',
                      (self.root / 'unregistered-schema.json').as_uri())
        for selected in manual.PLAYBOOK_IDS:
            for reference in references:
                with self.subTest(selected=selected, reference=reference):
                    try:
                        packet, scope = self.packet(selected)
                        schema = manual.board.read_json(self.root / manual.SCHEMA)
                        schema['properties']['task_key'] = {'$ref': reference}
                        self.write(manual.SCHEMA, schema)
                        self.rebind_all(packet, scope)
                        with patch('urllib.request.urlopen',
                                   side_effect=AssertionError('schema retrieval forbidden')) as fetch:
                            self.rejected(packet, scope, 'manual_schema_contract_invalid')
                            fetch.assert_not_called()
                        result = self.cli_fixture(packet, scope)
                        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                        self.assertEqual(json.loads(result.stdout), {'status': 'BLOCKED_INPUT',
                            'reason': 'manual_schema_contract_invalid', 'worker_invoked': False})
                        self.assertEqual(result.stderr, '')
                    finally:
                        (self.root / manual.SCHEMA).write_bytes(original)

    def test_valid_local_schema_references_preserve_prepare_only(self):
        original = (self.root / manual.SCHEMA).read_bytes()
        for selected in manual.PLAYBOOK_IDS:
            for keyword in ('$ref', '$dynamicRef'):
                with self.subTest(selected=selected, keyword=keyword):
                    try:
                        packet, scope = self.packet(selected)
                        schema = manual.board.read_json(self.root / manual.SCHEMA)
                        schema['$defs']['reviewedTaskKey'] = {'type': 'string', 'minLength': 1}
                        schema['properties']['task_key'] = {keyword: '#/$defs/reviewedTaskKey'}
                        self.write(manual.SCHEMA, schema)
                        self.rebind_all(packet, scope)
                        result = self.validate(packet, scope)
                        self.assertEqual(result['status'], 'VALIDATED_PREPARE_ONLY')
                        self.assertFalse(result['worker_invoked'])
                        self.assertFalse(result['completed_task'])
                        self.assertFalse(result['economic_authority'])
                        self.assertEqual(set(result['proof_results'].values()), {'NOT_RUN'})
                        manual.validate_shape(scope, scope=True, root=self.root)
                        cli = self.cli_fixture(packet, scope)
                        self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
                        self.assertEqual(json.loads(cli.stdout)['status'], 'VALIDATED_PREPARE_ONLY')
                        self.assertEqual(cli.stderr, '')
                    finally:
                        (self.root / manual.SCHEMA).write_bytes(original)

    def test_cli_preflight_is_non_executing_and_wrong_base_returns_two(self):
        # CLI reads canonical repo; packet/scope are ephemeral synthetic artifacts.
        _, row = manual.load_playbook('L0_RESUME_HANDOFF')
        dependencies = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                        for p in manual.required_dependencies(row['playbook_id'])}
        packet, scope = self.packet()
        packet['dependencies'] = copy.deepcopy(dependencies)
        scope['dependencies'] = dependencies
        self.bind(packet)
        self.write('packet.json', packet)
        self.write('scope.json', scope)
        command = [sys.executable, str(ROOT / 'tools/manual_foundation.py'),
                   '--packet', str(self.root / 'packet.json'), '--scope', str(self.root / 'scope.json'),
                   '--expected-base']
        good = subprocess.run(command + [BASE], capture_output=True, text=True)
        self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
        self.assertFalse(json.loads(good.stdout)['worker_invoked'])
        bad = subprocess.run(command + ['b' * 40], capture_output=True, text=True)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(json.loads(bad.stdout)['status'], 'BLOCKED_INPUT')


def main() -> int:
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ManualTests))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
