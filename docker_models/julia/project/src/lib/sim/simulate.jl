import Random
import CSV

include("pk.jl");

using DataFrames
using Distributions
using DeepCompartmentModels

rng = Random.Xoshiro(42)

nhanes = DataFrame(CSV.File("data/NHANES.csv", missingstring="NA"))
filter!(row -> row.Age <= 18 && row.Gender == "male" && !ismissing(row.Weight), nhanes)

N = (126, 57, 294, 12) # number of subjects per centre

for i in eachindex(N)
    tspan = (-0.1, 72.)
    if i == 1
        model = bjorkman
    elseif i == 2
        model = nesterov
        tspan = (-0.1, 168.)
    elseif i == 3
        model = mcenenyking
    else
        model = zhang
    end
    prob = ODEProblem(two_comp!, zeros(2), tspan)

    ids = sort(rand(rng, 1:nrow(nhanes), N[i]))
    x = nhanes[ids, [:Weight, :Age]]

    z, σ = model(rng, x)

    error_type = length(σ) == 2 ? CombinedError() : AdditiveError()

    df = DataFrame()
    for j in 1:size(z, 2)
        dose = round((x[j, :Weight] * 25) / 250) * 250
        if tspan[end] == 72
            t = Float64.(rand.((rng, ), [1:6, 10:18, 20:48]))
        else
            t = Float64.(rand.((rng, ), [1:6, 18:28, 36:72]))
        end

        zᵢ = z[:, j]
        prob_i = remake(prob, p = [zᵢ; 0.])

        callback = generate_dosing_callback([0 dose dose * 60 1/60], Float64)
        sol = solve(prob_i, saveat = t, save_idxs = 1, tstops = callback.condition.times, callback = callback)
        pred = sol.u
        noise = std(error_type, pred, (error = (; σ), ))
        y = max.(0, pred + rand(rng, MvNormal(zero(noise), noise)))

        append!(df, DataFrame(
            id = ids[j],
            time = [0; t],
            amt = [dose; fill(missing, length(y))],
            rate = [60 * dose; fill(missing, length(y))],
            duration = [1 / 60; fill(missing, length(y))],
            dv = [0; y],
            mdv = [1; zero(y)],
            wt = x[j, :Weight],
            age = x[j, :Age],
            cl = z[1, j],
            v1 = z[2, j],
            q = z[3, j],
            v2 = z[4, j],
        ))
    end

    CSV.write("data/simulated_data_centre_$i.csv", df)
end