# Julia Stage
FROM julia:1.11.7 AS julia-stage

# Copy Julia package files
WORKDIR /project
COPY project/Project.toml .
COPY project/Manifest.toml .

# Precompile Julia and install dependencies
RUN julia -e "using Pkg; \
    Pkg.activate(\".\"); \
    Pkg.instantiate(); \
    Pkg.precompile(timing = true)"

# Copy Julia code (maintain cache)
COPY project/src ./src

# Copy Julia data files (temp solution - ideally use volumes)
COPY project/data ./data

###############################

# Python Stage
FROM python:3.12-slim

RUN pip install dagster-pipes==1.11.10

# Copy Python code (maintain cache)
COPY entrypoint.py .

# Copy Julia project
COPY --from=julia-stage /project /project
# Copy Julia runtime
COPY --from=julia-stage /usr/local/julia /usr/local/julia
# Copy Julia package depot
COPY --from=julia-stage /root/.julia /root/.julia

# Set PATH to include Julia binaries
ENV PATH="/usr/local/julia/bin:${PATH}"

ENTRYPOINT ["python3", "entrypoint.py"]
