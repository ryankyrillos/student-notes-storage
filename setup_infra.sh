#!/bin/bash
set -e

export AWS_REGION=eu-north-1
aws configure set default.region $AWS_REGION

echo "Creating VPC..."
VPC_ID=$(aws ec2 create-vpc --cidr-block 10.0.0.0/16 --tag-specifications 'ResourceType=vpc,Tags=[{Key=Name,Value=StudentNotes-VPC}]' --query 'Vpc.VpcId' --output text)
aws ec2 modify-vpc-attribute --vpc-id $VPC_ID --enable-dns-hostnames
IGW_ID=$(aws ec2 create-internet-gateway --tag-specifications 'ResourceType=internet-gateway,Tags=[{Key=Name,Value=StudentNotes-IGW}]' --query 'InternetGateway.InternetGatewayId' --output text)
aws ec2 attach-internet-gateway --vpc-id $VPC_ID --internet-gateway-id $IGW_ID

echo "Creating Subnets..."
PUBLIC_SUBNET_1=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.1.0/24 --availability-zone ${AWS_REGION}a --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=Public-Subnet-1}]' --query 'Subnet.SubnetId' --output text)
PUBLIC_SUBNET_2=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.2.0/24 --availability-zone ${AWS_REGION}b --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=Public-Subnet-2}]' --query 'Subnet.SubnetId' --output text)
PRIVATE_SUBNET_1=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.3.0/24 --availability-zone ${AWS_REGION}a --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=Private-Subnet-1}]' --query 'Subnet.SubnetId' --output text)
PRIVATE_SUBNET_2=$(aws ec2 create-subnet --vpc-id $VPC_ID --cidr-block 10.0.4.0/24 --availability-zone ${AWS_REGION}b --tag-specifications 'ResourceType=subnet,Tags=[{Key=Name,Value=Private-Subnet-2}]' --query 'Subnet.SubnetId' --output text)

echo "Creating Route Table..."
PUBLIC_RT=$(aws ec2 create-route-table --vpc-id $VPC_ID --tag-specifications 'ResourceType=route-table,Tags=[{Key=Name,Value=Public-RT}]' --query 'RouteTable.RouteTableId' --output text)
aws ec2 create-route --route-table-id $PUBLIC_RT --destination-cidr-block 0.0.0.0/0 --gateway-id $IGW_ID
aws ec2 associate-route-table --route-table-id $PUBLIC_RT --subnet-id $PUBLIC_SUBNET_1
aws ec2 associate-route-table --route-table-id $PUBLIC_RT --subnet-id $PUBLIC_SUBNET_2

echo "Creating Security Groups..."
ALB_SG=$(aws ec2 create-security-group --group-name ALB-SG --description "Security group for Application Load Balancer" --vpc-id $VPC_ID --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id $ALB_SG --protocol tcp --port 80 --cidr 0.0.0.0/0
WEB_SG=$(aws ec2 create-security-group --group-name Web-SG --description "Security group for Web Servers" --vpc-id $VPC_ID --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id $WEB_SG --protocol tcp --port 8080 --source-group $ALB_SG
DB_SG=$(aws ec2 create-security-group --group-name DB-SG --description "Security group for RDS Database" --vpc-id $VPC_ID --query 'GroupId' --output text)
aws ec2 authorize-security-group-ingress --group-id $DB_SG --protocol tcp --port 3306 --source-group $WEB_SG

echo "Creating S3 Bucket..."
BUCKET_NAME="student-notes-$(date +%s)"
aws s3 mb s3://$BUCKET_NAME --region $AWS_REGION
aws s3api put-public-access-block --bucket $BUCKET_NAME --public-access-block-configuration "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

echo "Creating RDS..."
aws rds create-db-subnet-group --db-subnet-group-name studentnotes-db-subnet --db-subnet-group-description "Subnet group for Student Notes DB" --subnet-ids $PRIVATE_SUBNET_1 $PRIVATE_SUBNET_2
DB_PASSWORD="YourSecurePassword123!"
aws rds create-db-instance --db-instance-identifier studentnotes-db --db-instance-class db.t3.micro --engine mysql --master-username admin --master-user-password $DB_PASSWORD --allocated-storage 20 --vpc-security-group-ids $DB_SG --db-subnet-group-name studentnotes-db-subnet --backup-retention-period 1 --no-publicly-accessible

echo "Creating IAM Role..."
cat > ec2-trust-policy.json <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "ec2.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}
EOF
aws iam create-role --role-name EC2-StudentNotes-Role --assume-role-policy-document file://ec2-trust-policy.json || true
aws iam attach-role-policy --role-name EC2-StudentNotes-Role --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess
aws iam attach-role-policy --role-name EC2-StudentNotes-Role --policy-arn arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy
aws iam create-instance-profile --instance-profile-name EC2-StudentNotes-Profile || true
aws iam add-role-to-instance-profile --instance-profile-name EC2-StudentNotes-Profile --role-name EC2-StudentNotes-Role || true

echo "Saving Config..."
echo "VPC_ID=$VPC_ID" > aws-config.env
echo "PUBLIC_SUBNET_1=$PUBLIC_SUBNET_1" >> aws-config.env
echo "PUBLIC_SUBNET_2=$PUBLIC_SUBNET_2" >> aws-config.env
echo "PRIVATE_SUBNET_1=$PRIVATE_SUBNET_1" >> aws-config.env
echo "PRIVATE_SUBNET_2=$PRIVATE_SUBNET_2" >> aws-config.env
echo "ALB_SG=$ALB_SG" >> aws-config.env
echo "WEB_SG=$WEB_SG" >> aws-config.env
echo "DB_SG=$DB_SG" >> aws-config.env
echo "BUCKET_NAME=$BUCKET_NAME" >> aws-config.env
echo "DB_PASSWORD=$DB_PASSWORD" >> aws-config.env

echo "Setup Complete!"
