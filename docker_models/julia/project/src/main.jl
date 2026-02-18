import Random
import JSON

using Dates
using DeepCompartmentModels

include("lib/logging.jl")
include("lib/data.jl")
include("lib/optimise.jl")
include("lib/helpers.jl")

install_logger()

const SOURCE_PATH = "/project/data" # FIXME: Load from database or shared volume
const OUTPUT_PATH = required_env("ARTIFACT_PATH")


function process_dataset(
    dataset_name::String,
    source_dataset::String,
)
    @info "[JULIA] - Processing Dataset: $dataset_name"

    population = load_data(source_dataset)
    ps_opt = run_optimisation(population)

    output_path = joinpath(OUTPUT_PATH, dataset_name)
    isdir(output_path) || mkpath(output_path)

    filepath = joinpath(output_path, dataset_name * ".json")
    open(filepath, "w") do io
        JSON.print(io, ps_opt)
    end
end


function main()
    @info "RUNNING main.jl - processing all .csv files in $SOURCE_PATH"
    datasets = collect_datasets(SOURCE_PATH)
    @info "[JULIA] - Datasets Collected: $(keys(datasets))"

    for (dataset_name, source_dataset) in datasets
        process_dataset(dataset_name, source_dataset)
    end

    return 0
end


exit(main())
