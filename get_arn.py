import sys, json, subprocess
cmd = ["aws", "elbv2", "describe-listeners", "--load-balancer-arn", "arn:aws:elasticloadbalancing:eu-north-1:150215480207:loadbalancer/app/StudentNotes-ALB/da3d8dfc97489948", "--region", "eu-north-1", "--output", "json", "--no-cli-pager"]
out = subprocess.check_output(cmd)
j = json.loads(out)
arn = j['Listeners'][0]['ListenerArn']
with open('clean_arn.txt', 'w') as f:
    f.write(arn.strip())
print("ARN written to clean_arn.txt")
