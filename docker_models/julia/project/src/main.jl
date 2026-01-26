# Load packages:
@info "Loading packages..."

import Random
import JSON

using Dates
using DeepCompartmentModels

include("lib/data.jl");
include("lib/optimise.jl");
include("lib/helpers.jl");

const SOURCE_DATA_PATH = "/project/data"
const MNT_BASE_PATH = "/mnt/dagster/artifacts"
const TASK_ID = get(ENV, "TASK_ID", nothing)


function main(dataset_name::String)
    task_id = get(ENV, "TASK_ID", nothing)
    if task_id === nothing
        @error "[JULIA] - TASK_ID unset"
        return 1
    end

    source_dataset = "$(SOURCE_DATA_PATH)/$(dataset_name).csv"
    if !isfile(source_dataset)
        @error "[JULIA] - Source dataset not found: $(source_dataset)"
        return 1
    end

    population = load_data(source_dataset)
    ps_opt = run_optimisation(population)

    output_dir = "$(MNT_BASE_PATH)/$(task_id)/$(dataset_name)"
    isdir(output_dir) || mkpath(output_dir)
    filepath = joinpath(output_dir, "$(dataset_name).json")
    open(filepath, "w") do io
        JSON.print(io, ps_opt)
    end

    return 0
end

dataset_name = "simulated_data_centre_1"
@info "RUNNING main.jl - $(dataset_name)"
rc = main(dataset_name)
exit(rc)
