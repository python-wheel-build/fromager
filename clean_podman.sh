#!/bin/bash -x
# -*- indent-tabs-mode: nil; tab-width: 2; sh-indentation: 2; -*-

podman ps -a | grep 'e2e-' | awk '{print $1}' | while read -r container; do
  podman rm "$container"
done

podman images | awk '{print $1}' | grep e2e | while read -r image; do
  podman image rm "$image"
done

podman image prune --force
