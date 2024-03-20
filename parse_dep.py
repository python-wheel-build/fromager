#!/usr/bin/env python3

import sys

from packaging import requirements

req = requirements.Requirement(sys.argv[1])
print(req.name)
