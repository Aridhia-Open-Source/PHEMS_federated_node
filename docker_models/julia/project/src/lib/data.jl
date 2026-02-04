import CSV

using DataFrames

function load_data(path::AbstractString)
    df = DataFrame(CSV.File(path))
    df_group = groupby(df, :id)

    indvs = Vector{AbstractIndividual}(undef, length(df_group))
    for (i, group) in enumerate(df_group)
        x = Vector{Float32}(group[1, [:wt, :age]])
        I = Matrix{Float32}(group[isone.(group.mdv), [:time, :amt, :rate, :duration]])
        callback = generate_dosing_callback(I, Float32)
        ty = group[iszero.(group.mdv), [:time, :dv]]

        indvs[i] = Individual(x, Float32.(ty.time), Float32.(ty.dv), callback; initial = zeros(Float32, 2), id = group[1, :id])
    end

    return Population(indvs)
end