#!/bin/bash -x

podman ps -a | grep 'e2e-' | awk '{print $1}' | while read -r container; do
    podman rm "$container"
done

podman images | awk '{print $1}' | grep e2e | while read -r image; do
    podman image rm "$image"
done

podman image prune --force
