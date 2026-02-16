docker run --rm  --volume .:/data     --user $(id -u):$(id -g)     --env JOURNAL=joss     openjournals/inara
