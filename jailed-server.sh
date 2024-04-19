#!/bin/bash -x

JAIL_NAME=local-wheel-server

existing_pid=$(firejail --list | grep $JAIL_NAME | cut -f1 -d:)
if [ -n "$existing_pid" ]; then
    kill "$existing_pid"
    # Wait for jail to shutdown
    sleep 5
fi

mkdir -p ./wheels-repo/
firejail --net=none --name="$JAIL_NAME" python3 -m http.server -d ./wheels-repo/ &
