#!/bin/bash

# task_runner_user_data.sh.tpl

# Install necessary packages
sudo apt-get update
sudo apt-get -y install git binutils rustc cargo pkg-config libssl-dev python3-virtualenv python3-pip
git clone https://github.com/aws/efs-utils
cd efs-utils
./build-deb.sh
sudo apt-get -y install ./build/amazon-efs-utils*deb

echo "sleeping"
sleep 10

# Mount EFS using the specific access point ARN for write access
sudo id
sudo mkdir -p /data/cache
sudo chown ubuntu:ubuntu /data/cache
ls -la /data/cache

sleep 10

# Retry mount with delay to handle potential timing issues
RETRIES=5
for i in $(seq 1 $RETRIES); do
    echo "Attempting to mount EFS (Attempt $i of $RETRIES)..."

    # Mount the EFS using EFS Utils and Access Point ARN
    sudo mount -t efs -o tls,iam,accesspoint=${efs_access_point} ${efs_dns}:/ /data/cache

    # If mount succeeds, break out of the loop
    if mount | grep "/data/cache"; then
        echo "EFS mounted successfully."
        break
    fi

    echo "Mount failed, retrying in 10 seconds..."
    sleep 10
done

# Write the available models to a JSON file
sudo tee /data/cache/available_models.json > /dev/null << 'EOF_JSON'
${available_models_json}
EOF_JSON

# Write the library cache script to the usr dir
sudo tee /usr/local/bin/${library_cache_script_name} > /dev/null << 'EOF_BASH'
${library_cache_script}
EOF_BASH

# Write the model cache script to the usr dir
sudo tee /usr/local/bin/${model_cache_script_name} > /dev/null << 'EOF_PYTHON'
${model_cache_script}
EOF_PYTHON

# Ensure the script is executable
sudo chmod +x /usr/local/bin/${library_cache_script_name}

# Install the packages and download the models
# FIXME: get the HF_TOKEN from the env
export HF_TOKEN=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
export PIP_TARGET=/data/cache/packages/lib/python3.12/site-packages/
export CACHE_DIR=/data/cache/models
export HF_HUB_CACHE=/data/cache/models
cd /data/cache
sudo -E PATH=$PATH /usr/local/bin/${library_cache_script_name}
source packages/bin/activate
sudo -E PATH=$PATH python3 /usr/local/bin/${model_cache_script_name} /data/cache/available_models.json
deactivate

# Validate the data
#/usr/local/bin/validate_data.sh

# terminate the instance after completion
sudo shutdown 0
