# Platine Helm chart

Deploys Platine on Kubernetes: a hardened Deployment (non-root, read-only root filesystem, no
capabilities), a Service, and optionally an Ingress, an HTTPRoute (Gateway API), a NetworkPolicy and a
ServiceMonitor for Prometheus.

## Install

The chart and the image are published by the Platine CI on every `v*` tag:

```bash
helm install platine oci://ghcr.io/baptgosse/charts/platine -n platine --create-namespace
```

From a checkout, with an image you pushed yourself:

```bash
make push REGISTRY=ghcr.io/my-account TAG=2.0.0

helm upgrade --install platine charts/platine -n platine --create-namespace \
  --set image.repository=ghcr.io/my-account/platine \
  --set image.tag=2.0.0
```

`make helm-install REGISTRY=ghcr.io/my-account TAG=2.0.0` does the same.

Without an Ingress or an HTTPRoute, use a port-forward:

```bash
kubectl -n platine port-forward svc/platine 8320:80   # then http://localhost:8320
helm test platine -n platine                          # checks that /healthz answers
```

### Local cluster, no registry

```bash
make image TAG=dev
podman save localhost/platine:dev -o platine.tar

kind load image-archive platine.tar                   # kind
sudo k3s ctr images import platine.tar                # k3s

helm upgrade --install platine charts/platine -n platine --create-namespace \
  --set image.repository=localhost/platine --set image.tag=dev --set image.pullPolicy=Never
```

## Examples

Exposed through the Gateway API, with a password and a NetworkPolicy:

```yaml
# my-values.yaml
httpRoute:
  enabled: true
  parentRefs:
    - name: public-gateway
      namespace: gateway-system
      sectionName: https
  hostnames:
    - mp3.example.com
auth:
  enabled: true
  existingSecret: platine-auth   # kubectl create secret generic platine-auth --from-literal=username=me --from-literal=password=...
networkPolicy:
  enabled: true
```

With a classic Ingress:

```yaml
ingress:
  enabled: true
  className: traefik
  hosts:
    - host: mp3.example.com
      paths:
        - path: /
          pathType: Prefix
  tls:
    - secretName: mp3-tls
      hosts:
        - mp3.example.com
```

### Metrics

`/metrics` exposes the Prometheus metrics of Platine (HTTP requests, conversions). Like `/healthz`, it
is not password protected. With kube-prometheus-stack:

```yaml
metrics:
  serviceMonitor:
    enabled: true
    labels:
      release: kube-prometheus-stack
```

## Main values

| Value | Default | Purpose |
| --- | --- | --- |
| `image.repository` | `ghcr.io/baptgosse/platine` | Image to deploy |
| `image.tag` | appVersion | Image tag |
| `replicaCount` | `1` | Keep 1: downloads are tracked in memory, in the pod |
| `config.maxConcurrent` | `3` | Conversions running in parallel |
| `config.fileTTL` | `3600` | Seconds before a finished MP3 is deleted |
| `config.maxPlaylistItems` | `100` | Maximum tracks per playlist or album |
| `config.maxQueued` | `500` | Queued conversions beyond which the API answers 429 |
| `config.proxy` | `""` | Proxy for yt-dlp |
| `auth.enabled` | `false` | HTTP Basic password on everything except `/healthz` and `/metrics` |
| `auth.username` / `auth.password` | `platine` / `""` | Credentials, stored in a Secret created by the chart |
| `auth.existingSecret` | `""` | Existing Secret (keys `auth.usernameKey` and `auth.passwordKey`) |
| `cookies.existingSecret` | `""` | Secret holding a `cookies.txt` (key `cookies.key`), mounted read-only |
| `tmp.sizeLimit` | `2Gi` | Size limit of `/tmp` (downloads and finished MP3s) |
| `tmp.medium` | `""` | `Memory` for a tmpfs |
| `ingress.*` | disabled | Classic Ingress |
| `httpRoute.*` | disabled | Gateway API HTTPRoute |
| `networkPolicy.enabled` | `false` | Limits egress to DNS and the public Internet |
| `networkPolicy.ingress.from` | `[]` | Sources allowed on the http port (empty means all) |
| `metrics.podAnnotations` | `false` | `prometheus.io/*` annotations on the pod |
| `metrics.serviceMonitor.enabled` | `false` | ServiceMonitor (prometheus-operator) on `/metrics` |
| `metrics.serviceMonitor.labels` | `{}` | Labels expected by your Prometheus (e.g. `release: kube-prometheus-stack`) |
| `resources` | 100m / 256Mi, 1Gi limit | Container resources |
| `extraEnv` | `[]` | Extra variables (`valueFrom` allowed) |

The full list is in [`values.yaml`](values.yaml), validated by [`values.schema.json`](values.schema.json).

## Notes

- **One replica.** A download's progress and the resulting MP3 stay in the pod that handled it. With
  more replicas, configure cookie session affinity on the Ingress or Gateway.
- **NetworkPolicy.** Platine downloads any URL it is given. The policy blocks private ranges (10/8,
  172.16/12, 192.168/16, 169.254/16, fc00::/7) so it cannot be used to probe the internal network. If you
  use an internal proxy or NodeLocal DNS (169.254.20.10), add a rule under `networkPolicy.egress.extra`.
  The DNS selector targets `k8s-app: kube-dns` in `kube-system`; `networkPolicy.egress.dns: null` allows
  DNS to any destination. If you restrict `networkPolicy.ingress.from`, add the Prometheus namespace to
  keep scraping working.
- **yt-dlp updates.** Sites change often. Upgrade regularly (a new Platine tag ships the latest yt-dlp).
