# Migrating Compose Files to a Modular Docker Swarm Stack

## **Current Setup and Goal**

Your **AniTrend Local Stack** currently uses multiple Docker Compose files (one per component) that are started in sequence  . For example, Traefik (reverse proxy) is started first, then databases (Postgres, Mongo, Redis) individually, then observability services, and so on  . All services join a common external Docker network named **`traefik`** for inter-service communication , and many use named volumes for persistent data (e.g. Traefik SSL certs, Portainer data, database storage) . The goal is to **simplify deployment** by converting this into Docker Swarm stacks – effectively treating the entire environment as code (similar in spirit to Pulumi-managed infrastructure). This will allow you to spin up the whole stack easily on any Docker host (or swarm cluster), including local testing, with minimal manual orchestration.

## **Why Docker Swarm/Stack?**

Using Docker Swarm mode (via `docker stack deploy`) provides a declarative way to deploy multi-container apps. Instead of manually starting each Compose file in order, you can define *stacks* that encompass all services. Key benefits include:

- **Single-Step Deployment:** A stack file can bring up multiple services in one command, respecting dependencies and shared networks. This makes it easy to deploy the whole stack on a new host or cluster.
- **Modular Composition:** Swarm allows splitting services into multiple stack files by function (as you prefer: e.g. *infrastructure*, *observability*, *platform*). You can deploy each module independently or all together, while still leveraging a common overlay network for communication.
- **Consistency for Local and Cloud:** The same stack definitions can run on a single-node Swarm (e.g. your local dev machine) or a multi-node Swarm (e.g. your Hetzner VM cluster) without changing configurations. By initializing Docker in swarm mode on your local machine, you can test the entire stack exactly as it would run in production.
- **Foundation for IaC:** Expressing the setup in stack YAML files is a step toward full **Infrastructure as Code**. These files can be checked into version control and later managed by tools like Pulumi. (Pulumi can interact with Docker’s API to manage networks, volumes, and services, since the Docker provider works with Swarm mode as well .)

## **Modular Stack Design**

To meet your preference for functional separation, we will create **three stack files** (YAML) corresponding to different concerns. For example:

- **1. Infrastructure Stack:** Core services that underlie everything. This likely includes Traefik (edge router), Portainer (container management UI), the API Gateway (Apache APISIX plus its etcd backend), and foundational data stores (PostgreSQL, MongoDB, Redis). These are the building blocks of the environment. In your current setup, these were started first , so we group them as “infrastructure.”
- **2. Observability Stack:** All monitoring and logging components, e.g. Prometheus, Grafana, Loki, Tempo, and the OpenTelemetry collector. These services form the LGTM stack described in your README . They can be packaged together since they closely integrate (Grafana visualizes data from Prometheus/Loki/Tempo, etc.).
- **3. Platform Stack:** Application-level services and supporting tools. This would include things like GrowthBook (feature flag dashboard and proxy), your AniTrend application or any microservices (if containerized), and possibly edge computing services (contents of `on-the-edge/`) or other app-specific components. For example, in your manual steps you start GrowthBook’s services and then Portainer as “additional services” – these would fall under the *platform* module.

Each stack will have its own YAML file (e.g. `swarm-infrastructure.yml`, `swarm-observability.yml`, `swarm-platform.yml`). Splitting this way makes it easy to deploy or update each group separately. You can still launch **everything at once** with a small script or by running all three `docker stack deploy` commands, but modularizing gives flexibility (for instance, you might bring down or update the observability stack without touching the others).

## **Converting Compose Files to Stack Files**

Docker Swarm stack files use the **Compose v3** format, but some keys and patterns differ from a standalone Compose (`docker-compose up`) usage. Here’s how to rewrite your existing compose files for Swarm compatibility:

- **Use a Common Overlay Network:** Define the Traefik network as an external overlay network that all stacks will use. For example, in each stack file you might include at the bottom:
    
    ```yaml
    networks:
      default:
        name: traefik-public
        external: true
    
    ```
    
    This ensures all services join the same network (here we call it “traefik-public”). In your current Traefik compose, the default network is named “traefik” ; we can use a similarly consistent name across stacks (renaming it if desired). You will need to create this overlay network *once* before deploying any stack (e.g. `docker network create --driver=overlay --attachable traefik-public` on your swarm manager) . Using a single shared network means Traefik can route to containers from any stack, and services can communicate as needed. *(The `attachable` flag allows containers (e.g. one-off tasks or tools) to attach to the network if needed.)*
    
- **Consolidate and Reference Environment Variables:** Continue using your per-service `.env` files for configuration. In the stack file, use the `env_file` directive to load them (as in your original composes). For example, the Traefik service can specify `env_file: ./traefik/.env`. This way, domain names, credentials, and other settings remain in those .env files and can be tweaked per environment without altering the stack YAML.
- **Define Named Volumes (External if Needed):** In Swarm, volumes can be declared at the top level of the YAML. For any service data you want to persist or share, define a named volume. If you have existing data volumes from your Compose setup that you want to reuse, mark them as `external: true` with the same name. For example, Traefik’s TLS certificate store volume and Portainer’s data volume should be preserved. In the infrastructure stack file, you might have:
    
    ```yaml
    volumes:
      traefik-ssl-certs:
        name: traefik_traefik-ssl-certs
        external: true
      portainer-data:
        name: portainer_portainer-data
        external: true
      etcd-data:
        name: etcd-data
        external: true
      apisix-cache:
        name: apisix-cache
        # (external: true if you want to reuse an existing cache volume)
    
    ```
    
    This snippet (based on your draft swarm file) defines volumes by name  . The `external: true` tells Swarm to use the volume if it exists (or require it to be created beforehand), rather than making a new one. For new volumes (like a cache or fresh DB storage), you can omit `external` – Docker will create them on deploy. Similarly, in the observability stack, you’d define volumes for Prometheus data, Loki data, Grafana storage, etc.  . Mark those as external if you need to retain data between stack deployments; otherwise, let Swarm manage them (it will create named volumes that persist until you remove them).
    
- **Remove Unsupported Compose Keys:** Some options used in Docker Compose are not supported in swarm mode. Notably, **`container_name`** and the standalone **`restart`** policy should be removed . Swarm will auto-generate container names based on the stack and service name, and restart behavior can be controlled via a deploy policy. For example, in your Traefik compose you set a container\_name and `restart: unless-stopped` ; in the stack file these lines are omitted. (Swarm will by default restart containers on failure, and you can specify a `deploy.restart_policy` if needed.) By removing the container\_name constraint, you allow Swarm to scale or reschedule services freely (unique container names per instance) . Similarly, options like `build:` in Compose files should be replaced with an explicit `image:` reference, since `docker stack deploy` cannot build images on the fly . Ensure all images are either public or in a registry accessible to your swarm nodes.
- **Add Deploy Configurations:** The `deploy:` section is specific to Swarm and lets you configure how the service runs in the cluster. You can specify replicas (or `mode: global`), placement constraints, resource limits, etc. In your case, since you want one instance of each service (at least initially) and likely will run on a single node, you could use `deploy.mode: global` for each service. This ensures one container per node (on a one-node swarm, it’s one instance) . You already drafted this in your `swarm.infrastructure.yml` – for example, Traefik and Portainer are set to global with a constraint to run only on manager nodes . The manager-node constraint is useful if you ever add worker nodes but want these core services to stick to the primary node. Here’s an excerpt illustrating this for Traefik in the stack file:
    
    ```yaml
    services:
      traefik:
        image: traefik:v3.5
        deploy:
          mode: global
          placement:
            constraints:
              - node.role == manager
        networks:
          default:
            aliases:
              - traefik
        ports:
          - 80:80
          - 443:443
        env_file: ./traefik/.env
        volumes:
          - traefik-ssl-certs:/etc/traefik/certs
          - ./traefik/auth/htpasswd:/etc/htpasswd:ro
          - ./traefik/config/traefik.yml:/etc/traefik/traefik.yml:ro
          - ./traefik/config/dynamic.yml:/etc/traefik/dynamic.yml:ro
          - /var/run/docker.sock:/var/run/docker.sock:ro
        labels:
          - "traefik.enable=${TRAEFIK_ENABLE}"
          - "traefik.http.routers.traefik-ui.rule=Host(`${HOST}`)"
          ... (TLS and middleware labels) ...
          - "traefik.http.services.traefik-ui.loadbalancer.server.port=${PORT}"
    
    ```
    
    In this snippet, `deploy.mode: global` with a manager constraint is used for Traefik , and the service is attached to the `traefik-public` network via the default network (with an alias for internal DNS) . We’ve omitted `restart` and `container_name`, and instead rely on Swarm’s management. If you prefer to run a specific number of instances rather than one-per-node, you could use `mode: replicated` and `replicas: N` under deploy. For example, if you wanted 3 replicas of a stateless service, you could set that. For now, one of each is fine. (All your observability and core services can remain singletons unless scaling is needed. The stack file for observability similarly uses `mode: global` for each component  , effectively one instance of each on the manager.)
    
- **Service Dependencies:** In Compose, you might have used `depends_on` to order startups. Swarm mode **does support `depends_on` for start order** (it waits until a dependent service is **attempted** to start, but not necessarily fully healthy). You can include them in the stack file for clarity. For instance, your observability stack file indicates the OTel collector should start after Loki, Tempo, and Prometheus , and Grafana after Prom/Tempo/Loki . In the infrastructure stack, your APISIX Dashboard depends on the gateway and Traefik being up . These `depends_on` entries will ensure Docker brings up services in a sensible order, though remember they don’t guarantee the target is ready – for robust waiting you’d need healthchecks (which could be added via `deploy.healthcheck` if necessary). Given that you want ease of spinning up the whole stack, having these in place will reduce race conditions (e.g. Grafana starting before Prometheus might just result in some data sources erroring until Prometheus comes up, but not critical).
- **Traefik Labels and Networking:** Continue to use Traefik labels on services to configure routing. These labels carry over fine in Swarm (Traefik will pick them up via Docker API). In the stack files, ensure each service that should be exposed has the appropriate labels (as in your current compose files). For example, the Prometheus service in the observability stack has labels for Traefik routing , and these remain the same format. Just double-check that any reference to Docker-specific notation (like `sso@docker` middleware in labels ) still works in Swarm – it should, as long as Traefik is running in the same swarm and attached to the network (Traefik will see services on the network). All stacks share the `traefik-public` network, so Traefik can route to any service in any stack.

By following the above steps, you’ll end up with stack definition files that codify your entire environment. As an example, your **observability stack file** might start like this (based on the one you have drafted):

```yaml
# swarm-observability.yml
volumes:
  prometheus-data:
    name: prometheus-data
    driver: local
  loki-data:
    name: loki-data
    driver: local
  tempo-data:
    name: tempo-data
    driver: local
  grafana-data:
    name: grafana-data
    driver: local

services:
  prometheus:
    image: prom/prometheus:v2.55.1
    deploy:
      mode: global
      placement:
        constraints:
          - node.role == manager
      restart_policy:
        condition: any
    volumes:
      - ./observability/prometheus/config/:/etc/prometheus/
      - prometheus-data:/prometheus
    env_file: ./observability/prometheus/.env
    labels:
      - "traefik.http.routers.prometheus.rule=Host(`${HOST}`)"
      - "traefik.http.routers.prometheus.entrypoints=web,websecure"
      - "traefik.http.routers.prometheus.service=prometheus"
      - "traefik.http.routers.prometheus.tls=true"
      - "traefik.http.routers.prometheus.tls.certresolver=${CERT_RESOLVER}"
      - "traefik.http.services.prometheus.loadbalancer.server.port=${PORT}"
    logging:
      options:
        max-size: "10m"
        max-file: "3"

  grafana:
    image: grafana/grafana-oss:11.5.2
    deploy:
      mode: global
      placement:
        constraints:
          - node.role == manager
      restart_policy:
        condition: any
    volumes:
      - grafana-data:/var/lib/grafana
      - ./observability/grafana/config/provisioning/:/etc/grafana/provisioning/
    env_file: ./observability/grafana/.env
    depends_on:
      - prometheus
      - loki
      - tempo
    labels:
      - "traefik.http.routers.grafana.rule=Host(`${HOST}`)"
      - "traefik.http.routers.grafana.entrypoints=web,websecure"
      - "traefik.http.routers.grafana.service=grafana"
      - "traefik.http.routers.grafana.tls=true"
      - "traefik.http.routers.grafana.tls.certresolver=${CERT_RESOLVER}"
      - "traefik.http.services.grafana.loadbalancer.server.port=${PORT}"
    ...

networks:
  default:
    name: traefik-public
    external: true

```

In this snippet, you can see how volumes are defined for each data store (not marked external here, meaning the stack will create them)  , and each service is configured similarly to the original compose but with Swarm-compatible keys (no `container_name`, using `deploy` for restart policy, etc.)  . All services join the `traefik-public` network  so that Traefik (from the infra stack) can route to them via the labels.

## **Deployment Workflow**

Once you have the stack files ready, using them is straightforward:

1. **Initialize Swarm (once):** On any Docker host (local or remote) that will run the stack, enable swarm mode if not already: `docker swarm init`. If you have multiple nodes, join them to the swarm. Create the shared overlay network that spans the swarm:
    
    ```bash
    docker network create --driver=overlay --attachable traefik-public
    
    ```
    
    This sets up the **`traefik-public`** network across all swarm nodes[github.com](https://github.com/studiomitte/traefik-swarm#:~:text=Create%20docker%20overlay%20network). (The name must match the one used in your stack files’ network definition.)
    
2. **Deploy the Stacks:** Use `docker stack deploy` for each module. For example:
    
    ```bash
    docker stack deploy -c swarm-infrastructure.yml infrastructure
    docker stack deploy -c swarm-observability.yml observability
    docker stack deploy -c swarm-platform.yml platform
    
    ```
    
    You can choose any names for the stacks (`infrastructure`, `observability`, `platform` here are just identifiers). Docker will read the YAML, create any needed networks/volumes, then instantiate the services. Because we marked the `traefik-public` network as external, the stack deploy will use the pre-created overlay network to attach services (it won’t try to create a new one). Each service will come up according to the order and constraints specified. You might deploy the **infrastructure stack first**, so that Traefik, databases, and Portainer are running; then deploy platform (which might include apps that depend on the databases or gateway); and finally deploy observability to start monitoring everything. In practice, these could be almost simultaneous, but doing infra first ensures core services are ready for the others.
    
3. **Verification:** Once deployed, use `docker stack services <stack_name>` to see that all services are running. You can also use Portainer (now running as a service on the swarm) to visually inspect the stacks and their containers. All the URLs (Traefik dashboard, Grafana, Prometheus, APISIX Dashboard, GrowthBook, etc.) should be accessible at their configured domains just as before[GitHub](https://github.com/AniTrend/local-stack/blob/0b48edb62ba46afd2f1f08653f9adf1a4840ccaa/README.md#L182-L190) – Traefik is still handling routing. The difference is that now Traefik runs as a swarm service and it discovers other services via the overlay network and Docker metadata.
4. **Local Testing:** For running everything locally, you can follow the same steps on your development machine. After `docker swarm init` (which just converts your single Docker engine into a one-node swarm), deploy the same stack files. The services will behave the same way on your laptop. You might need to adjust some config (for example, use a local domain or `/etc/hosts` entries for the host rules, or disable certain TLS settings if you don’t have certs locally). But since the stack is parameterized by the .env files, you could set `HOST=localhost` or similar in those when testing locally, or use something like `nip.io` wildcard DNS. The key is that the infrastructure as code is consistent – you’re not maintaining a separate Compose for local dev; it’s the same stack definitions, increasing confidence that “if it works here, it works in prod.”
    
    ## **Pulumi Integration (Infrastructure as Code)**
    
    Moving to Docker Swarm stacks already gives you infrastructure-as-code benefits: your entire setup is described in version-controlled YAML files. If you want to go one step further and use **Pulumi** (or similar IaC tools) to manage this stack, you have a couple of options:
    
    - **Pulumi Docker Provider:** Pulumi has a Docker provider that can manage Docker resources via the Docker API. It’s compatible with Swarm mode[pulumi.com](https://www.pulumi.com/registry/packages/docker/#:~:text=The%20Docker%20provider%20is%20used,compatible%20API%20hosts). In Pulumi, you could write code to ensure the overlay network exists, create volumes, and even instantiate each service container. Essentially, Pulumi would do what the stack file does – you’d define each container (service) in Pulumi code. This might be somewhat duplicative of the stack YAML, but it offers the full power of a programming language (looping over similar services, using config files, etc.). For example, you could use Pulumi to deploy the same services by creating `docker.Container` resources for each service, specifying networks, images, etc., or use `docker.Service` if provided for swarm services.
    - **Pulumi Automation for Stacks:** Another approach is to treat the Docker stack deploy command as an external action orchestrated by Pulumi. For instance, Pulumi could provision the VM (if using cloud infrastructure), install Docker, initialize the swarm, then run `docker stack deploy` using the stack files that live in your repo. This could be done via Pulumi’s automation API or using the command-line program execution within your Pulumi script. This way, you leverage the stack YAML directly. Pulumi becomes the one orchestrating *when and where* to deploy the stack, but the stack contents remain in the YAML. This approach is useful if you want Pulumi to manage higher-level infrastructure (like cloud instances, networks, DNS records pointing to your Traefik, etc.) while still using Docker’s native stack capability for the containers.
    
    Since your end goal is to manage infrastructure with Pulumi, you might start by **embedding these stack files into Pulumi**. For example, you could store the YAML in Pulumi (or read from files) and use the Pulumi Docker provider to create equivalent services. The Pulumi Docker provider can create networks and volumes easily, but creating a full stack might require defining each service as a `Service` or `Container` resource in code. The provider is low-level (container-by-container), whereas Docker Compose/Stack is a higher-level grouping. Evaluate which approach makes sense: if the stack isn’t too large, coding it in Pulumi could be fine; if you prefer to keep using the YAML, use Pulumi for the layers around it (provisioning machines, triggering deployments, etc.).
    
    Regardless of Pulumi, **the hard part (defining everything as code) is now done** with your Docker Swarm configs. You can gradually fold this into Pulumi at your own pace. The immediate win is that deploying your environment is as simple as running a few commands, and everything is defined declaratively in the stack files. This modular, Docker Swarm-based setup will make your infrastructure more portable and easier to manage, whether manually or via Pulumi in the future.
    
    ## **Conclusion**
    
    By rewriting your Docker Compose files into Docker Swarm stack files, you achieve a more robust and portable setup. We split the stack into logical modules (*infrastructure, observability,* and *platform*) to keep things organized, but all services share a common overlay network for seamless connectivity [github.com](https://github.com/studiomitte/traefik-swarm#:~:text=,www%20to%20www). The new YAML definitions remove Compose-only directives and instead leverage Swarm features like the deploy section for scheduling [GitHub](https://github.com/AniTrend/local-stack/blob/0b48edb62ba46afd2f1f08653f9adf1a4840ccaa/swarm.infrastructure.yml#L18-L26) [stackoverflow.com](https://stackoverflow.com/questions/51454349/docker-docker-compose-file-for-docker-stack-deploy#:~:text=Ignoring%20unsupported%20options%3A%20build%2C%20restart). You can now bring up the entire AniTrend local stack on any machine (or cluster) with just a few commands, and tear it down just as easily, without manual per-directory orchestration. This not only simplifies your workflow (e.g., one command to start all monitoring services instead of five) but also lays the groundwork for treating your setup as true infrastructure-as-code. In the future, Pulumi or other IaC tools can manage these stacks, but even on its own, this Docker Swarm approach will give you a self-documenting, reproducible environment.
    
    **Sources:**
    
    - AniTrend/local-stack README – describes current multi-Compose setup and project structure [GitHub](https://github.com/AniTrend/local-stack/blob/0b48edb62ba46afd2f1f08653f9adf1a4840ccaa/README.md#L140-L148) [GitHub](https://github.com/AniTrend/local-stack/blob/0b48edb62ba46afd2f1f08653f9adf1a4840ccaa/README.md#L165-L173).
    - Example Docker Swarm stack file (in progress) for infrastructure – shows global services, external network, etc. [GitHub](https://github.com/AniTrend/local-stack/blob/0b48edb62ba46afd2f1f08653f9adf1a4840ccaa/swarm.infrastructure.yml#L18-L26) [GitHub](https://github.com/AniTrend/local-stack/blob/0b48edb62ba46afd2f1f08653f9adf1a4840ccaa/swarm.infrastructure.yml#L162-L166).
    - Example Swarm stack file for observability – demonstrates volume definitions and service configurations in swarm mode [GitHub](https://github.com/AniTrend/local-stack/blob/0b48edb62ba46afd2f1f08653f9adf1a4840ccaa/swarm.observerability.yml#L2-L10) [GitHub](https://github.com/AniTrend/local-stack/blob/0b48edb62ba46afd2f1f08653f9adf1a4840ccaa/swarm.observerability.yml#L181-L184).
    - Docker Swarm & Traefik best practices – using a shared overlay network “traefik-public” for all stacks [github.com](https://github.com/studiomitte/traefik-swarm#:~:text=,www%20to%20www)[github.com](https://github.com/studiomitte/traefik-swarm#:~:text=Create%20docker%20overlay%20network).
    - Docker Compose vs Swarm differences – note about unsupported options like `container_name` and `restart` in stack deployments [stackoverflow.com](https://stackoverflow.com/questions/51454349/docker-docker-compose-file-for-docker-stack-deploy#:~:text=Ignoring%20unsupported%20options%3A%20build%2C%20restart).
    - Pulumi Docker provider docs – confirms Pulumi can interact with Docker Swarm resources via the Docker API [pulumi.com](https://www.pulumi.com/registry/packages/docker/#:~:text=The%20Docker%20provider%20is%20used,compatible%20API%20hosts).