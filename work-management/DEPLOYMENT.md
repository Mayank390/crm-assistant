# Deployment Guide

Quick guide for deploying the PMS Assistant application to the development server.

## Prerequisites

- SSH access configured (see `~/.ssh/config`)
- Docker and Docker Compose installed on the server
- Access to Azure Container Registry (if using ACR images)

## Server Access

### SSH into the server

```bash
ssh simpo-dev
```

The server is configured in your SSH config:
- **Host**: `simpo-dev`
- **Hostname**: `172.171.192.172`
- **User**: `harshith`
- **Port**: `22`

### Navigate to project directory

```bash
cd /home/devsimpouser/planboard-ai
```

## Deployment Methods

### Option 1: Deploy using ACR Images (Recommended)

1. **Build and push images from local machine**:
   ```bash
   # From your local machine
   cd /Users/harshith/pms-assistant
   ./deploy.sh v1.0.0  # Replace with your version
   ```

2. **SSH into server and set environment variables**:
   ```bash
   ssh simpo-dev
   cd /home/devsimpouser/planboard-ai
   
   export ACR_REGISTRY=aiplanboard.azurecr.io
   export IMAGE_PREFIX=aiplanboard
   export IMAGE_TAG=v1.0.0  # Use the version you pushed
   ```

3. **Login to ACR**:
   ```bash
   az acr login --name aiplanboard
   # OR
   docker login aiplanboard.azurecr.io
   ```

4. **Pull latest images and deploy**:
   ```bash
   docker-compose pull
   docker-compose up -d
   ```

### Option 2: Build on Server

1. **SSH into server**:
   ```bash
   ssh simpo-dev
   cd /home/devsimpouser/planboard-ai
   ```

2. **Pull latest code**:
   ```bash
   git pull origin stage  # or your branch
   ```

3. **Ensure .env file is configured**:
   ```bash
   # Edit .env with your production settings
   nano .env
   ```

4. **Build and deploy**:
   ```bash
   # Don't set ACR_REGISTRY to build locally
   unset ACR_REGISTRY
   docker-compose build
   docker-compose up -d
   ```

## Managing Deployment

### Check service status

```bash
docker-compose ps
```

### View logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f backend
docker-compose logs -f embedding
docker-compose logs -f consumer
```

### Stop services

```bash
docker-compose down
```

### Restart services

```bash
docker-compose restart
# Or restart specific service
docker-compose restart backend
```

### Update deployment

```bash
# Pull latest code
git pull origin stage

# Rebuild and restart
docker-compose up -d --build

# Or if using ACR images
docker-compose pull
docker-compose up -d
```

## Service Endpoints

Once deployed, services are available at:

- **Backend API**: `http://172.171.192.172:8000`
- **Kafka UI**: `http://172.171.192.172:8084`
- **Qdrant**: `http://172.171.192.172:6333`
- **Embedding Service**: `http://172.171.192.172:8081`
- **SPLADE Service**: `http://172.171.192.172:8082`

## Environment Variables

Ensure your `.env` file includes:

```bash
# MongoDB
MONGODB_URI=mongodb://...
MONGODB_DATABASE=ProjectManagement

# Qdrant
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=...

# HuggingFace (for model access)
HF_TOKEN=...

# Models
EMBEDDING_MODEL=google/embeddinggemma-300m
SPLADE_MODEL_NAME=naver/splade-cocondenser-ensembledistil

# Kafka
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
KAFKA_TOPIC_PREFIX=ProjectManagement.
```

## Troubleshooting

### Check if services are running

```bash
docker-compose ps
```

### Check container logs

```bash
docker-compose logs backend
docker-compose logs embedding
```

### Check system resources

```bash
# Check disk space
df -h

# Check memory
free -h

# Check Docker resources
docker system df
```

### Restart failed services

```bash
docker-compose up -d --force-recreate <service-name>
```

### Clean up Docker resources

```bash
# Remove unused containers, networks, images
docker system prune -a

# Remove volumes (WARNING: deletes data)
docker volume prune
```

## Quick Reference

```bash
# SSH into server
ssh simpo-dev

# Navigate to project
cd /home/devsimpouser/planboard-ai

# Deploy
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down

# Update
git pull && docker-compose up -d --build

#disk
df -h
```

