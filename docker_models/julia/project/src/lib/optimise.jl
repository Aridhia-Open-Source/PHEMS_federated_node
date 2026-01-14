import Accessors
import Optim

_pk(::AbstractVector) = Float32[0.15, 3., 0.15, 0.75]
_pk(x::AbstractMatrix) = Float32[0.15, 3., 0.15, 0.75] .* ones(4, size(x, 2))

function get_model()
    # Dummy Neural Network:
    nn = Lux.Chain(
        Lux.WrappedFunction(_pk)
    ) # just predicts same pk parameters for all data examples
    # Differential Equation:
    prob = ODEProblem(two_comp!, zeros(Float32, 2), (-0.1f0, 1.f0))

    return DCM(prob, nn, CombinedError())
end

function set_parameters(ps, st)
    # Set suitable parameters:
    ps = merge(ps, (phi = (μ = zeros(Float32, 2), ), ))
    ps = merge(ps, (omega = Float32[0.06 0.03; 0.03 0.04], ))
    ps = merge(ps, (error = (σ = Float32[1., 0.125], ), ))
    st = merge(st, (phi = (epsilon = zeros(Float32, 2), mask = st.phi.mask, ), ))

    return ps, st
end

function objective(dcm, individual, ps, st)
    ζ, _ = dcm.model(individual.x, ps.theta, st.theta)
    z = ζ .* exp.(st.phi.mask * ps.phi.μ)
    ŷ = forward_ode_with_dv(dcm, individual, [z; zero(Float32)])
    dist = MvNormal(ŷ, std(dcm, ŷ, ps))
    prior = MvNormal(zeros(Float32, size(ps.omega, 1)), ps.omega)
    return -(logpdf(dist, individual.y) + logpdf(prior, ps.phi.μ))
end

function run_optimisation(population::Population)
    dcm = get_model()

    ps_, st_ = setup(VariationalELBO([1,2]), dcm, population)
    ps, st = set_parameters(ps_, st_)

    map_estimates = map(population) do individual
        optimise_individual(dcm, individual, ps, st)
    end

    ps_opt = merge(ps, (phi = (mode = reduce(hcat, map_estimates), ), ))
    return (ps = ps_opt, st = st, )
end


function optimise_individual(dcm, individual::AbstractIndividual, ps, st)
    print("Optimising for individual id = $(individual.id)")
    opt = Optim.optimize(zeros(Float32, 2)) do η
        ps_i = Accessors.@set ps.phi.μ = η
        objective(dcm, individual, ps_i, st)
    end
    println(" DONE!")

    return opt.minimizer
end