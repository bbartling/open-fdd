## Mega nuke prune

### 1) Stop everything

```bash
docker ps -aq | xargs -r docker stop
```

### 2) Remove all containers

```bash
docker ps -aq | xargs -r docker rm -f
```

### 3) Remove all images

```bash
docker images -aq | xargs -r docker rmi -f
```

### 4) Remove all volumes (THIS deletes DB data)

```bash
docker volume ls -q | xargs -r docker volume rm -f
```

### 5) Remove all custom networks

```bash
docker network ls --format '{{.Name}}' | grep -vE '^(bridge|host|none)$' | xargs -r docker network rm
```

### 6) Final system prune (build cache, leftovers)

```bash
docker system prune -a --volumes -f
docker builder prune -a -f
```




