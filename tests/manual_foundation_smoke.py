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
        # Historical catalog positives must not silently follow later code.
        # Restore only the exact reviewed Lake bytes inside this temporary root.
        # Current-source refusal is tested separately; production lookup is intact.
        catalog = manual.load_catalog(self.root)
        if any(row['classification'] == 'REUSE_NOW' and
               row['dependency_hashes'].get('tools/long_history_lake.py') == HISTORICAL_LAKE_SHA256
               for row in catalog['entries']):
            (self.root / 'tools/long_history_lake.py').write_bytes(historical_lake_fixture_bytes())
        for name, (expected_sha, _, _) in HISTORICAL_READER_INPUTS.items():
            if any(row['classification'] == 'REUSE_NOW' and
                   row['dependency_hashes'].get(name) == expected_sha
                   for row in catalog['entries']):
                # Restore only the temporary historical positive, never the
                # checked-out source or the catalog's reviewed dependency pins.
                (self.root / name).write_bytes(historical_reader_fixture_bytes(name))
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
        before = (self.root / manual.CATALOG).read_bytes()
        for name, (expected, _, _) in HISTORICAL_READER_INPUTS.items():
            self.assertEqual(hashlib.sha256((self.root / name).read_bytes()).hexdigest(), expected)
        for entry in ('group_423_574', 'group_591'):
            self.assertTrue(manual.lookup_reuse(entry, self.root)['allowed'])
        self.assertEqual((self.root / manual.CATALOG).read_bytes(), before)

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
        self.assertTrue(manual.lookup_reuse('group_591', self.root)['allowed'])
        (self.root / 'tools/research_data_access.py').write_text('CHANGED')
        with self.assertRaisesRegex(manual.ContractError, 'catalog_dependency_changed'):
            manual.lookup_reuse('group_591', self.root)

    def test_selective_port_and_historical_are_not_automatic_reuse(self):
        for key in ('group_400_405', 'group_586', 'group_1'):
            self.assertFalse(manual.lookup_reuse(key, self.root)['allowed'])
            packet, scope = self.packet()
            packet['reuse_entries'] = [key]
            self.rejected(self.bind(packet), scope, 'catalog_reuse_not_allowed')

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
        self.assertEqual(len(registered_validation.DEFAULT_TESTS), 235)
        required = set(manual.required_dependencies('A6_INDEPENDENT_QA', self.root))
        self.assertTrue(programs.issubset(required), sorted(programs - required))
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
