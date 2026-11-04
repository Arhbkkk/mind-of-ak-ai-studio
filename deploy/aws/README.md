# AWS starter deployment

This is a single-EC2 Docker Compose starter: FastAPI and a dedicated render worker share a persistent Docker volume on the EC2 EBS disk. SQLite is for one host only, not a multi-instance production database.

## Cost warning

AWS is not guaranteed to be permanently free. EC2, EBS, public IPv4, data transfer, snapshots, logs and tax can incur charges. Eligibility and quotas depend on your account, region and current offer. Verify pricing and create a small AWS Budget alert before provisioning. A budget alert is not a spending cap. Do not add NAT Gateway, RDS, ElastiCache, GPU instances or load balancers for this starter.

A micro instance is only suitable for development and short low-resolution renders. FFmpeg is CPU and memory intensive. The Compose default sets `MAX_RENDER_EDGE=640`; on a larger instance, increase this environment variable (for example, 1920) only after load-testing memory and render times. The selected resolution in the UI cannot exceed this configured long-edge cap.

## Deployment

1. Create an AWS Budget alert in Billing.
2. Select an EC2 instance eligible for your account offer; verify regional pricing.
3. Use Ubuntu LTS and an encrypted EBS volume.
4. Restrict SSH port 22 to your own IP. Do not expose port 8000 publicly.
5. Install Docker Engine and Docker Compose using the official Ubuntu instructions.
6. Clone this repository and run `docker compose up -d --build`.
7. Check `docker compose ps` and `docker compose logs -f web worker`.
8. Verify `curl http://127.0.0.1:8000/api/health` on the instance.
9. For private testing, create an SSH tunnel: `ssh -L 8000:127.0.0.1:8000 ubuntu@EC2_PUBLIC_IP`, then open `http://127.0.0.1:8000` locally.

## Security limitations

The app currently has no authentication, authorization, per-user quotas, CSRF protection or malware scanning. Do not expose it publicly or upload private footage. Add authentication, TLS, request limits, abuse protection, backups and a security review before public exposure. A domain and TLS proxy may cost extra.

## Persistence and scaling

The Docker volume stores jobs, uploads and exports on the EC2 disk. EBS is not a backup. Keep one worker on a micro instance. Monitor CPU, memory, disk and billing. The queue is bounded; worker state is durable, but current progress is queued/running/completed rather than exact frame percentage. At scale, migrate to SQS, private S3 and separately scaled workers; these services are not assumed free.


## Optional GitHub Actions deployment

The repository includes `.github/workflows/deploy-aws.yml`. It deploys on pushes to `main` or manual workflow dispatch, but only after the EC2 host is provisioned and GitHub repository secrets are configured.

Add these under **Repository → Settings → Secrets and variables → Actions → New repository secret**:

- `AWS_EC2_HOST`: EC2 public DNS name or static public IP.
- `AWS_EC2_USER`: Ubuntu AMI login user, commonly `ubuntu`.
- `AWS_EC2_SSH_KEY`: private SSH key for a dedicated deployment key (never commit it).
- `AWS_EC2_KNOWN_HOSTS`: verified SSH host-key line for the EC2 host. Obtain and verify the fingerprint through a trusted AWS/console channel; do not blindly trust an unverified `ssh-keyscan` result.

Before enabling this workflow, clone the repository on EC2 into `$HOME/mind-of-ak-ai-studio`, configure Docker Compose, and verify that the deployment user can run Docker without an interactive password. Restrict the security group and keep port 8000 private. The workflow deliberately fails closed when any secret is missing. It does not create AWS infrastructure or configure billing.
