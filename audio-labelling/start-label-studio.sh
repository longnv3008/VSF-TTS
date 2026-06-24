docker run -d --restart always -it -p 8080:8080 -v $(pwd)/data:/label-studio/data \
--env LABEL_STUDIO_LOCAL_FILES_SERVING_ENABLED=true \
--env LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT=/label-studio/files \
-v $(pwd)/files:/label-studio/files --name label-studio \
heartexlabs/label-studio:latest label-studio

