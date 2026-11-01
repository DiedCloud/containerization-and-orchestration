{{- define "shop.placement" -}}
{{- if .Values.placement.enabled }}
{{- $selector := dict "app.kubernetes.io/name" "api" "app.kubernetes.io/instance" .Release.Name }}
{{- if eq .Values.placement.mechanism "topologySpreadConstraints" }}
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: {{ .Values.placement.topologyKey }}
    whenUnsatisfiable: DoNotSchedule
    minDomains: 2
    matchLabelKeys: [pod-template-hash]
    labelSelector:
      matchLabels:
        {{- toYaml $selector | nindent 8 }}
{{- else if eq .Values.placement.mechanism "podAntiAffinity" }}
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - topologyKey: {{ .Values.placement.topologyKey }}
        labelSelector:
          matchLabels:
            {{- toYaml $selector | nindent 12 }}
{{- else }}
{{- fail "placement.mechanism must be topologySpreadConstraints or podAntiAffinity" }}
{{- end }}
{{- end }}
{{- end }}
