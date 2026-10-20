{{/* Short chart name. */}}
{{- define "platine.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/* Full resource name: <release>-<chart>, or <release> when it already contains the chart name. */}}
{{- define "platine.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "platine.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "platine.labels" -}}
helm.sh/chart: {{ include "platine.chart" . }}
{{ include "platine.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "platine.selectorLabels" -}}
app.kubernetes.io/name: {{ include "platine.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "platine.serviceAccountName" -}}
{{- if .Values.serviceAccount.create }}
{{- default (include "platine.fullname" .) .Values.serviceAccount.name }}
{{- else }}
{{- default "default" .Values.serviceAccount.name }}
{{- end }}
{{- end }}

{{- define "platine.image" -}}
{{- printf "%s:%s" .Values.image.repository (default .Chart.AppVersion .Values.image.tag) }}
{{- end }}

{{/* Secret holding the HTTP Basic credentials: the one provided, or the one created by the chart. */}}
{{- define "platine.authSecretName" -}}
{{- default (printf "%s-auth" (include "platine.fullname" .)) .Values.auth.existingSecret }}
{{- end }}
