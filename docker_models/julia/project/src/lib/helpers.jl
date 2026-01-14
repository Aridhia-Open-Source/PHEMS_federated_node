function handle_args(args::AbstractVector{<:String})
    data_path_idx = findfirst(Base.Fix2(startswith, "--data="), args)
    if isnothing(data_path_idx)
        data_path_idx = findfirst(endswith(".csv"), args)
        if isnothing(data_path_idx)
            throw(ErrorException(
                "Data path not supplied to script. Specify data location via --data argument: `julia --project=. --data=/my/path/data.csv`"
            ))
        end
    end

    data_path = split(args[data_path_idx], "--data=")[end]
    @info "Using data from: $(data_path)"

    @assert endswith(data_path, ".csv") "data file is not a CSV file"
    @assert isfile(data_path) "data path does not link to existing file"

    ckpt_path_idx = findfirst(Base.Fix2(startswith, "--ckpt="), args)
    if isnothing(ckpt_path_idx)
        ckpt_path_idx = findfirst(endswith(".json"), args)
        if isnothing(ckpt_path_idx)
            throw(ErrorException(
                "Checkpoint path not supplied to script. Specify checkpoint output location via --ckpt argument: `julia --project=. --ckpt=/my/checkpoint.json`"
            ))
        end
    end
    ckpt_path = split(args[ckpt_path_idx], "--ckpt=")[end]
    @assert endswith(ckpt_path, ".json") "checkpoint path does not point to JSON file"

    return (data = data_path, ckpt = ckpt_path)
end

