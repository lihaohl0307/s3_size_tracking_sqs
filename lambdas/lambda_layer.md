## Docker
# create a layer working folder
mkdir -p layer/python

# use the official lambda runtime image to install into /opt/python
docker run --rm -v "$PWD/layer:/opt" public.ecr.aws/lambda/python:3.13 \
  /bin/sh -lc "python -m pip install --upgrade pip && pip install matplotlib -t /opt/python"

# zip it (zip must contain the top-level 'python/' dir)
cd layer
zip -r ../matplotlib-py313-layer.zip python
cd ..

# Reference to debug
https://github.com/docker/for-mac/issues/7527


## Build the layer(x86_64)
---------------------------------------------------------------------------------
# Clean any old container
docker rm -f build313 2>/dev/null || true

# Build inside Lambda's py3.13 image for x86_64
docker run --platform linux/amd64 --name build313 \
  --entrypoint /bin/sh public.ecr.aws/lambda/python:3.13 -c '
set -eux
python -m pip install --upgrade pip
# Force wheels only; fail if a source build would be needed
pip install --no-cache-dir --only-binary=:all: \
  "numpy>=2.1,<2.3" "matplotlib>=3.9.2,<3.11" "pillow>=10,<11" -t /opt/python

# Prove imports work from /opt/python
PYTHONPATH=/opt/python python - << "EOF"
import numpy, matplotlib, PIL, contourpy, kiwisolver
print("OK numpy", numpy.__version__)
print("OK matplotlib", matplotlib.__version__)
print("OK pillow", PIL.__version__)
EOF
'

# Copy files out and zip (must have top-level 'python/' folder)
rm -rf layer && mkdir -p layer
docker cp build313:/opt/python ./layer/python
docker rm -f build313

cd layer && zip -r ../matplotlib-py313-x86-layer.zip python && cd ..
unzip -l matplotlib-py313-x86-layer.zip | head -n 60    # should list lots under python/
