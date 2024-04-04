#!/bin/bash -x

firejail --net=none --name=local-wheel-server python -m http.server -d ./wheels-repo/
