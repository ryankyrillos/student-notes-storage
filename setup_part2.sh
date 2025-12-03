#!/bin/bash
set -e

# Load config from Part 1
source aws-config.env

echo "Creating User Data Script..."
GITHUB_REPO="https://github.com/ryankyrillos/student-notes-storage.git"

cat > user-data.sh <<EOF
#!/bin/bash
yum update -y
yum install python3 python3-pip git mysql -y

cd /home/ec2-user
git clone $GITHUB_REPO app
cd app

pip3 install -r requirements.txt
pip3 install gunicorn

export RDS_HOST="$RDS_ENDPOINT"
export RDS_USER="admin"
export RDS_PASSWORD="$DB_PASSWORD"
export RDS_DB="studentnotes"
export S3_BUCKET="$BUCKET_NAME"
export FLASK_SECRET_KEY="flask-secret-\$(date +%s)"

# Wait for RDS to be ready (simple retry)
until mysql -h \$RDS_HOST -u \$RDS_USER -p\$RDS_PASSWORD -e "SELECT 1"; do
  echo "Waiting for database..."
  sleep 10
done

mysql -h \$RDS_HOST -u \$RDS_USER -p\$RDS_PASSWORD < schema.sql

cat > /etc/systemd/system/studentnotes.service <<SVCEOF
[Unit]
Description=Student Notes Flask App
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/app
Environment="RDS_HOST=\$RDS_HOST"
Environment="RDS_USER=\$RDS_USER"
Environment="RDS_PASSWORD=\$RDS_PASSWORD"
Environment="RDS_DB=\$RDS_DB"
Environment="S3_BUCKET=\$S3_BUCKET"
Environment="FLASK_SECRET_KEY=\$FLASK_SECRET_KEY"
ExecStart=/usr/local/bin/gunicorn -w 4 -b 0.0.0.0:8080 app:app
Restart=always

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable studentnotes
systemctl start studentnotes
EOF

echo "Creating Launch Template..."
AMI_ID=$(aws ec2 describe-images --owners amazon --filters "Name=name,Values=al2023-ami-2023.*-x86_64" --query 'Images | sort_by(@, &CreationDate) | [-1].ImageId' --output text)
aws ec2 create-launch-template --launch-template-name StudentNotes-LT --version-description "Initial version" --launch-template-data "{\"ImageId\":\"$AMI_ID\",\"InstanceType\":\"t3.micro\",\"IamInstanceProfile\":{\"Name\":\"EC2-StudentNotes-Profile\"},\"SecurityGroupIds\":[\"$WEB_SG\"],\"UserData\":\"$(base64 -w 0 user-data.sh)\",\"TagSpecifications\":[{\"ResourceType\":\"instance\",\"Tags\":[{\"Key\":\"Name\",\"Value\":\"StudentNotes-Instance\"}]}]}"

echo "Creating Load Balancer..."
ALB_ARN=$(aws elbv2 create-load-balancer --name StudentNotes-ALB --subnets $PUBLIC_SUBNET_1 $PUBLIC_SUBNET_2 --security-groups $ALB_SG --scheme internet-facing --type application --ip-address-type ipv4 --query 'LoadBalancers[0].LoadBalancerArn' --output text)
TG_ARN=$(aws elbv2 create-target-group --name StudentNotes-TG --protocol HTTP --port 8080 --vpc-id $VPC_ID --health-check-path / --health-check-interval-seconds 30 --query 'TargetGroups[0].TargetGroupArn' --output text)
aws elbv2 create-listener --load-balancer-arn $ALB_ARN --protocol HTTP --port 80 --default-actions Type=forward,TargetGroupArn=$TG_ARN

echo "Creating Auto Scaling Group..."
aws autoscaling create-auto-scaling-group --auto-scaling-group-name StudentNotes-ASG --launch-template LaunchTemplateName=StudentNotes-LT,Version='$Latest' --min-size 1 --max-size 3 --desired-capacity 1 --vpc-zone-identifier "$PRIVATE_SUBNET_1,$PRIVATE_SUBNET_2" --target-group-arns $TG_ARN --health-check-type ELB --health-check-grace-period 300
aws autoscaling put-scaling-policy --auto-scaling-group-name StudentNotes-ASG --policy-name CPU-ScaleOut --policy-type TargetTrackingScaling --target-tracking-configuration '{"PredefinedMetricSpecification": {"PredefinedMetricType": "ASGAverageCPUUtilization"}, "TargetValue": 70.0}'

echo "Creating CloudWatch Alarms..."
aws cloudwatch put-metric-alarm --alarm-name StudentNotes-HighCPU --metric-name CPUUtilization --namespace AWS/EC2 --statistic Average --period 300 --threshold 70 --comparison-operator GreaterThanThreshold --evaluation-periods 2 --dimensions Name=AutoScalingGroupName,Value=StudentNotes-ASG
aws cloudwatch put-metric-alarm --alarm-name StudentNotes-BillingAlarm --metric-name EstimatedCharges --namespace AWS/Billing --statistic Maximum --period 21600 --threshold 5 --comparison-operator GreaterThanThreshold --evaluation-periods 1 --dimensions Name=Currency,Value=USD

echo "Waiting for ALB DNS..."
sleep 10
ALB_DNS=$(aws elbv2 describe-load-balancers --load-balancer-arns $ALB_ARN --query 'LoadBalancers[0].DNSName' --output text)
echo "--------------------------------------------------"
echo "Deployment Complete!"
echo "Application URL: http://$ALB_DNS"
echo "--------------------------------------------------"
