FROM python:3.6-alpine
MAINTAINER Nathan Suberi <nathan.suberi@wri.org>

# install core libraries
RUN apk update
RUN apk add git

# install application libraries
RUN pip install --upgrade pip && pip install requests
RUN pip install -e git+https://github.com/fgassert/cartosql.py.git#egg=cartosql

# Env
ARG NAME=nrt-script
ENV NAME ${NAME}

# Copy the application folder inside the container
RUN mkdir -p /opt/$NAME/data
WORKDIR /opt/$NAME/
COPY contents/ .
COPY time.cron .
VOLUME ./data

# Set user for container security
USER root
RUN adduser -D $NAME
RUN chown -R $NAME:$NAME .
USER $NAME

# Launch script
CMD ["python", "main.py"]
