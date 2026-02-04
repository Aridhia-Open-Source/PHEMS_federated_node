import LinearAlgebra: Symmetric

cv_to_omega2(cv) = log((cv/100)^2 + 1)

"""
Model from McEneny-King et al., Development and evaluation of a generic population pharmacokinetic model for standard half-life factor VIII for use in dose individualization
Slightly simplified:
cl (L/h)  = 0.238 * (wt/70)^0.794 * (1 - 0.205 * max(0, (age - 21) / 21)) * exp(eta1)
v1 (L)    = 3.01 * (wt/70)^1.02 * exp(eta2)
q  (L/h)  = 0.142
v2 (L)    = 0.525 * (wt/70)^0.787

CV(%)     = [41.1, 32.4], ρ = 0.703
σ (IU/dL) = [0.5, 0.174]

All parameters are converted to dL in the below function
"""
function mcenenyking(rng, x::DataFrame)
    n = nrow(x)
    
    C = [1 0.703; 0.703 1]
    ω² = cv_to_omega2.([41.1, 32.4])
    Ω = Symmetric(sqrt.(ω²) .* C .* sqrt.(ω²))
    eta_prior = MvNormal(zeros(2), Ω)
    eta = rand(rng, eta_prior, n)
    
    wt = x.Weight
    age = x.Age

    cl = @. 10 * 0.238 * (wt/70)^0.794 * (1 - 0.205 * max(0, (age - 21) / 21)) * exp(eta[1, :])
    v1 = @. 10 * 3.01 * (wt/70)^1.02 * exp(eta[2, :])
    q  = fill(10 * 0.142, n)
    v2 = @. 0.525 * (wt/70)^0.787

    σ = [0.5, 0.174]

    return transpose(hcat(cl, v1, q, v2)), σ
end

"""
Model from Björkman et al., Population pharmacokinetics of recombinant factor VIII: the relationships of pharmacokinetics to age and body weight

cl (mL/h) = 193 * (wt/56)^0.8 * (1 - 0.0045 * (age - 22)) * exp(eta1)
v1 (L)    = 2.22 * (wt/56)^0.95 * exp(eta2)
q  (mL/h) = 147
v2 (L)    = 0.73 * (wt/56)^0.76

CV(%)     = [30, 21], ρ = 0.45
σ (IU/dL) = [8.9]

All parameters are converted to dL in the below function
"""
function bjorkman(rng, x::DataFrame)
    n = nrow(x)
    
    C = [1 0.45; 0.45 1]
    ω² = cv_to_omega2.([30, 21])
    Ω = Symmetric(sqrt.(ω²) .* C .* sqrt.(ω²))
    eta_prior = MvNormal(zeros(2), Ω)
    eta = rand(rng, eta_prior, n)
    
    wt = x.Weight
    age = x.Age

    cl = @. 0.01 * 193 * (wt/56)^0.8 * (1 - 0.0045 * (age - 22)) * exp(eta[1, :])
    v1 = @. 10 * 2.22 * (wt/56)^0.95 * exp(eta[2, :])
    q  = fill(0.01 * 147, n)
    v2 = @. 10 * 0.73 * (wt/56)^0.76
    σ = [8.9]

    return transpose(hcat(cl, v1, q, v2)), σ
end

"""
Model from Nesterov et al., The pharmacokinetics of a B‐domain truncated recombinant factor VIII, turoctocog alfa (NovoEight®), in patients with hemophilia A

cl (dL/h) = 1.63 * exp(eta1)
v1 (dL)   = 37.9 * (wt/73)^0.448 * exp(eta2)
q  (dL/h) = 0.0742
v2 (dL)   = 6.77

CV(%)     = [29.3, 13.5], ρ = 0.464
σ (IU/dL) = [0.3, 0.137]
"""
function nesterov(rng, x::DataFrame)
    n = nrow(x)
    
    C = [1 0.464; 0.464 1]
    ω² = cv_to_omega2.([29.3, 13.5])
    Ω = Symmetric(sqrt.(ω²) .* C .* sqrt.(ω²))
    eta_prior = MvNormal(zeros(2), Ω)
    eta = rand(rng, eta_prior, n)
    
    wt = x.Weight

    cl = @. 1.63 * exp(eta[1, :])
    v1 = @. 37.9 * (wt/73)^0.448 * exp(eta[2, :])
    q  = fill(0.0742, n)
    v2 = fill(6.77, n)
    σ = [0.3, 0.137]

    return transpose(hcat(cl, v1, q, v2)), σ
end


"""
Model from Zhang et al., Population pharmacokinetics of recombinant coagulation factor VIII‐SingleChain in patients with severe hemophilia A

cl (dL/h) = 2.12 * (wt/68)^0.756
v1 (dL)   = 33.6 * (wt/68)^0.903
q  (dL/h) = 1.34
v2 (dL)   = 2.65

ω²        = [0.0583, 0.0388], ρ = 0.5
σ (IU/dL) = [1.15, 0.109]
"""
function zhang(rng, x::DataFrame)
    n = nrow(x)
    
    C = [1 0.5; 0.5 1]
    ω² = [0.0583, 0.0388]
    Ω = Symmetric(sqrt.(ω²) .* C .* sqrt.(ω²))
    eta_prior = MvNormal(zeros(2), Ω)
    eta = rand(rng, eta_prior, n)
    
    wt = x.Weight

    cl = @. 2.12 * (wt/68)^0.756 * exp(eta[1, :])
    v1 = @. 33.6 * (wt/68)^0.903 * exp(eta[2, :])
    q  = fill(1.34, n)
    v2 = fill(2.65, n)
    σ = [1.15, 0.109]

    return transpose(hcat(cl, v1, q, v2)), σ
end