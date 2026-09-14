# Local, verified Ubuntu 22.04 / ROS2 Humble dependency image.
# See README.md for provenance and rebuilding the dependency base.
FROM botdog-dev-66671b4ca1:humble
USER root
COPY environment.sh /usr/local/bin/beijing-env
RUN chmod +x /usr/local/bin/beijing-env \
    && sed -i s,botdog-env,beijing-env,g /home/developer/.bashrc
USER developer
WORKDIR /workspace/project
ENTRYPOINT ["/usr/local/bin/beijing-env"]
CMD ["sleep", "infinity"]
