#!/bin/bash
set -e

PROJECT_ID="dionysus-ai-synthesis-project"
REGION="us-west1"
ZONE="us-west1-a"
ADDRESS_NAME="telnyx-bridge-ip"
INSTANCE_NAME="telnyx-bridge-vm"

echo "[*] Setting gcloud project to $PROJECT_ID..."
gcloud config set project $PROJECT_ID

echo "[*] Reserving Static IP: $ADDRESS_NAME in $REGION..."
# Check if address already exists
if gcloud compute addresses list --filter="name=$ADDRESS_NAME" --format="value(name)" | grep -q "$ADDRESS_NAME"; then
    echo "    Static IP $ADDRESS_NAME already exists."
else
    gcloud compute addresses create $ADDRESS_NAME --region=$REGION
fi

# Get the reserved IP address
STATIC_IP=$(gcloud compute addresses describe $ADDRESS_NAME --region=$REGION --format="value(address)")
echo "    Reserved IP address is: $STATIC_IP"

echo "[*] Creating firewall rules to allow HTTP and HTTPS traffic..."
if gcloud compute firewall-rules list --filter="name=default-allow-http" --format="value(name)" | grep -q "default-allow-http"; then
    echo "    Firewall rule default-allow-http already exists."
else
    gcloud compute firewall-rules create default-allow-http \
        --direction=INGRESS \
        --priority=1000 \
        --network=default \
        --action=ALLOW \
        --rules=tcp:80 \
        --source-ranges=0.0.0.0/0 \
        --target-tags=http-server
fi

if gcloud compute firewall-rules list --filter="name=default-allow-https" --format="value(name)" | grep -q "default-allow-https"; then
    echo "    Firewall rule default-allow-https already exists."
else
    gcloud compute firewall-rules create default-allow-https \
        --direction=INGRESS \
        --priority=1000 \
        --network=default \
        --action=ALLOW \
        --rules=tcp:443 \
        --source-ranges=0.0.0.0/0 \
        --target-tags=https-server
fi

echo "[*] Provisioning GCE Instance: $INSTANCE_NAME (e2-micro) in $ZONE..."
# Check if instance already exists
if gcloud compute instances list --filter="name=$INSTANCE_NAME" --format="value(name)" | grep -q "$INSTANCE_NAME"; then
    echo "    Instance $INSTANCE_NAME already exists."
else
    gcloud compute instances create $INSTANCE_NAME \
        --zone=$ZONE \
        --machine-type=e2-micro \
        --address=$ADDRESS_NAME \
        --image-family=debian-11 \
        --image-project=debian-cloud \
        --tags=http-server,https-server \
        --metadata=startup-script="apt-get update && apt-get install -y python3-pip python3-venv git nginx"
fi

echo "============================================================"
echo "🎉 GCE VM PROVISIONED SUCCESSFULLY!"
echo "   VM Name: $INSTANCE_NAME"
echo "   Static IP: $STATIC_IP"
echo "============================================================"
