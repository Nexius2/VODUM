-- Detect legacy parent names from schema metadata only, without scanning rows.
SELECT DISTINCT fk."table"
FROM sqlite_master AS schema
JOIN pragma_foreign_key_list(schema.name) AS fk
WHERE schema.type = 'table'
  AND (substr(lower(fk."table"), -4) = '_old'
       OR substr(lower(fk."table"), -9) = '__rebuild')
ORDER BY fk."table";
