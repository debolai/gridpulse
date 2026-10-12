{{- define "gridpulse.image" -}}
{{ .root.Values.image.registry }}/gridpulse/{{ .component }}:{{ .root.Values.image.tag }}
{{- end -}}

{{- define "gridpulse.labels" -}}
app.kubernetes.io/part-of: gridpulse
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "gridpulse.securityContext" -}}
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: false
  capabilities:
    drop: ["ALL"]
{{- end -}}
