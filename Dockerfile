# BlueOS extension: Coverage Logger.
#
# Conventions learned the hard way from the QuickStart template (see
# blueboat-docker/HANDOFF-and-STATUS.md):
#  - explicit WORKDIR + explicit uvicorn module path: app startup must never
#    depend on cwd-based autodiscovery
#  - code lives at /srv/app, NOT /app, and the permissions label binds only a
#    data directory — QuickStart ships a broken $IMAGE_NAME bind that shadows
#    /app with an empty dir and crash-loops litestar
FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    --extra-index-url https://www.piwheels.org/simple
COPY app /srv/app

ENV DATA_DIR=/data
EXPOSE 8000/tcp

LABEL version="0.2.0"
LABEL permissions='\
{\
  "ExposedPorts": {\
    "8000/tcp": {}\
  },\
  "HostConfig": {\
    "Binds": ["/usr/blueos/extensions/coverage-logger:/data"],\
    "ExtraHosts": ["host.docker.internal:host-gateway"],\
    "PortBindings": {\
      "8000/tcp": [{"HostPort": ""}]\
    }\
  }\
}'
LABEL authors='[{"name": "Kevin Griffin", "email": "papa.legba404@gmail.com"}]'
LABEL company='{"about": "Survey coverage QC for BlueBoat", "name": "Kevin Griffin", "email": "papa.legba404@gmail.com"}'
LABEL type="tool"
LABEL readme='https://raw.githubusercontent.com/KevinGriffin-new/blueos-coverage-logger/{tag}/README.md'
LABEL links='{"source": "https://github.com/KevinGriffin-new/blueos-coverage-logger"}'
LABEL requirements="core >= 1.1"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
