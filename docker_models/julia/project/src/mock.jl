@info "[SUBPROC][JULIA][INFO] Loading packages..."

import Random
import JSON

using Dates
using DeepCompartmentModels

include("lib/data.jl");
include("lib/optimise.jl");
include("lib/helpers.jl");

const MNT_BASE_PATH = "/mnt/dagster/artifacts"


function mock_results(count::Int)
    # Read TASK_ID from env
    task_id = get(ENV, "TASK_ID", nothing)
    if task_id === nothing
        @error "[SUBPROC][JULIA][ERROR] - TASK_ID unset"
        return 1
    end

    output_dir = "$(MNT_BASE_PATH)/$(task_id)"
    isdir(output_dir) || mkpath(output_dir)

    for n in 1:count
        filepath = "$(output_dir)/result_$(n).json"
        @info "[SUBPROC][JULIA][INFO] - Creating file ($n): $filepath"

        data = Dict("result" => Dict("value" => n))
        open(filepath, "w") do io
            JSON.print(io, data)
        end
    end

    return 0
end


function main()
    argv = Base.ARGS
    @info "[SUBPROC][JULIA][INFO] - Executing main()"
    @info "[SUBPROC][JULIA][INFO] - argv: $argv"
    return mock_results(5)
end


@info "[SUBPROC][JULIA][INFO] - START main.jl"
rc = main()
exit(rc)
