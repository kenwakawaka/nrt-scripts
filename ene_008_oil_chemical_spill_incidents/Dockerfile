FROM python:3.6-alpine
MAINTAINER Nathan Suberi <nathan.suberi@wri.org>

# install core libraries
RUN apk update
RUN apk add git
RUN pip install --upgrade pip

# install application libraries
RUN pip install requests
RUN pip install -e git+https://github.com/fgassert/cartosql.py.git#egg=cartosql

# env
ARG NAME=ene_008
ENV NAME ${NAME}

# Copy the application folder inside the container
RUN mkdir -p /opt/$NAME/data
WORKDIR /opt/$NAME/
COPY contents/ .
COPY time.cron .

# Set user for container security
RUN adduser -D $NAME
RUN chown -R $NAME /opt/$NAME/
USER $NAME
VOLUME ./data

# Launch script
CMD ["python", "main.py"]
