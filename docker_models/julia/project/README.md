# PoC Haemophilia model

This repo contains the code for running a simple local job on a federated network.

The Julia code for the model to find MAP estimates of random effect posteriors can be run using the following command:

```bash
julia --project=. src/main.jl --data=DATA_PATH --ckpt=CKPT_PATH
```

Here, the user is expected to supply two arguments:

`DATA_PATH`: the path pointing to a .csv file containing the data. Dummy data is available under the `/data` folder.

`CKPT_PATH`: the path where the resulting .json file is saved.

Each node should have its own local data set. This specific model performs a local job, meaning that the result is specific
to that node. The central node thus only needs to aggregate the data by concatenating the results from each node. Alternatively,
the central node stores the result from each node in a object pointing to that specific node.

An example in pseudo-code:

```julia
results = map(nodes) do node
    run_local_job(data_path[node], ckpt_path[node]) # returns the result.json
end

concat(results)
# or 
result = NamedTuple(node_1 = results[1], node_2 = results[2], ) # etc.
```



