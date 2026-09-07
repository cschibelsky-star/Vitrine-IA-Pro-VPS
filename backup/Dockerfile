FROM alpine:3.20

RUN apk add --no-cache bash coreutils docker-cli jq rclone tzdata

WORKDIR /opt/vitrine-backup
COPY backup/backup-agent.sh /opt/vitrine-backup/backup-agent.sh
RUN chmod 0755 /opt/vitrine-backup/backup-agent.sh

ENV TZ=America/Sao_Paulo \
    BACKUP_INTERVAL_SECONDS=21600 \
    RCLONE_REMOTE=vitrine-drive \
    RCLONE_PREFIX=Vitrine-IA-Pro-Backups

ENTRYPOINT ["/opt/vitrine-backup/backup-agent.sh"]
