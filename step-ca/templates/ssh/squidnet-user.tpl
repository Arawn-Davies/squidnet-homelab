{{- if ne (lower (toString .Token.email)) "you@example.com" }}{{ fail "this account may not get SQUIDNET SSH certificates" }}{{- end }}
{
	"type": "user",
	"keyId": {{ toJson .Token.email }},
	"principals": ["root", "arawn"],
	"extensions": {{ toJson .Extensions }},
	"criticalOptions": {{ toJson .CriticalOptions }}
}
