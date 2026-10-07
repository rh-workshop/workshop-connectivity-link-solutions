#!/usr/bin/python
# -*- coding: utf-8 -*-
# Módulo auxiliar del taller: consulta un nombre en TODOS los servidores
# autoritativos de su zona (sin recursión) y dice si todos lo publican.
# Existe porque community.dns.nameserver_record_info sigue el CNAME del propio
# nombre y acaba preguntando a los NS de la zona del balanceador (elb.amazonaws.com).

from __future__ import absolute_import, division, print_function
__metaclass__ = type

DOCUMENTATION = r"""
module: wk_dns_autoritativo
short_description: Comprueba que todos los NS autoritativos publican un nombre
description:
  - Localiza la zona del nombre (primer ancestro con SOA propio), obtiene sus NS y
    pregunta a cada uno por los registros A y CNAME del nombre, sin recursión.
options:
  nombre:
    description: Nombre DNS a comprobar.
    required: true
    type: str
  zona:
    description: Zona autoritativa. Si se omite se detecta subiendo por el nombre.
    type: str
  timeout:
    description: Segundos por consulta.
    type: float
    default: 5
requirements: [dnspython]
"""

RETURN = r"""
zona: {description: Zona autoritativa usada, type: str, returned: always}
respuestas: {description: Registros por servidor, type: dict, returned: always}
publicado: {description: Todos los NS devuelven al menos un A o CNAME, type: bool, returned: always}
"""

from ansible.module_utils.basic import AnsibleModule

try:
    import dns.message
    import dns.name
    import dns.query
    import dns.rdatatype
    import dns.resolver
    HAS_DNS = True
except ImportError:
    HAS_DNS = False


def detectar_zona(nombre):
    etiquetas = nombre.rstrip(".").split(".")
    for i in range(1, len(etiquetas) - 1):
        candidata = ".".join(etiquetas[i:])
        try:
            respuesta = dns.resolver.resolve(candidata, "SOA", raise_on_no_answer=False)
        except (dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            continue
        if respuesta.rrset is not None and respuesta.rrset.name == dns.name.from_text(candidata):
            return candidata
    return None


def consultar(servidor_ip, nombre, tipo, timeout):
    consulta = dns.message.make_query(nombre, tipo)
    consulta.flags &= ~0x0100  # sin recursión (RD=0)
    respuesta = dns.query.udp(consulta, servidor_ip, timeout=timeout)
    valores = []
    for rrset in respuesta.answer:
        if rrset.rdtype in (dns.rdatatype.A, dns.rdatatype.CNAME):
            valores.extend(r.to_text() for r in rrset)
    return valores


def main():
    modulo = AnsibleModule(
        argument_spec=dict(
            nombre=dict(type="str", required=True),
            zona=dict(type="str"),
            timeout=dict(type="float", default=5),
        ),
        supports_check_mode=True,
    )
    if not HAS_DNS:
        modulo.fail_json(msg="Falta la librería dnspython en el Python de Ansible.")

    nombre = modulo.params["nombre"]
    zona = modulo.params["zona"] or detectar_zona(nombre)
    if not zona:
        modulo.fail_json(msg="No se encontró la zona autoritativa de %s" % nombre)

    respuestas = {}
    try:
        servidores = [r.to_text() for r in dns.resolver.resolve(zona, "NS")]
        for servidor in servidores:
            ip = dns.resolver.resolve(servidor, "A")[0].to_text()
            try:
                respuestas[servidor] = consultar(ip, nombre, "A", modulo.params["timeout"])
            except Exception as error:  # timeout de un NS concreto: cuenta como no publicado
                respuestas[servidor] = ["error: %s" % error]
    except Exception as error:
        modulo.fail_json(msg="Error consultando los NS de %s: %s" % (zona, error))

    publicado = bool(respuestas) and all(
        v and not any(x.startswith("error:") for x in v) for v in respuestas.values()
    )
    modulo.exit_json(changed=False, zona=zona, respuestas=respuestas, publicado=publicado)


if __name__ == "__main__":
    main()
