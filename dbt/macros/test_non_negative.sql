{#- Generic test: column must be >= 0. Written locally to keep the project
    free of package dependencies. -#}
{% test non_negative(model, column_name) %}
    select {{ column_name }}
    from {{ model }}
    where {{ column_name }} < 0
{% endtest %}
