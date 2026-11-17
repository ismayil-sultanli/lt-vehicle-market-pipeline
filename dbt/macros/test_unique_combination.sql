{#- Generic test: the given column combination is the grain of the model. -#}
{% test unique_combination(model, columns) %}
    select {{ columns | join(', ') }}
    from {{ model }}
    group by {{ columns | join(', ') }}
    having count(*) > 1
{% endtest %}
