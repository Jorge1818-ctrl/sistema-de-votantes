                "Domicilio": domicilio.strip(),
                "Seccion": seccion.strip(),
                "Partido": otro.strip() if partido == "Otro" else partido,
                "Autorizacion": "Sí"
            }
            datos = pd.concat([datos, pd.DataFrame([nuevo])], ignore_index=True)
            guardar_datos(datos)
            st.success("Persona registrada y guardada en votantes.csv.")
            st.rerun()


elif opcion == "Consultar registros":
    st.subheader("Consultar personas")
    if datos.empty:
        st.info("No hay registros.")
    else:
        busqueda = st.text_input("Buscar por nombre")
        filtrados = datos[
            datos["Nombre"].str.contains(busqueda, case=False, na=False, regex=False)
        ]
        st.dataframe(
            filtrados.drop(columns=["Autorizacion"]),
            use_container_width=True,
            hide_index=True
        )
        st.download_button(
            "Descargar registros CSV",
            data=filtrados.to_csv(index=False).encode("utf-8-sig"),
            file_name="registros_votantes.csv",
            mime="text/csv"
        )


elif opcion == "Eliminar persona":
    st.subheader("Eliminar registro")
    if datos.empty:
        st.info("No hay registros que eliminar.")
    else:
        opciones_registro = {
            f"{fila['Nombre']} | Sección {fila['Seccion']} | ID: {fila['ID']}": fila["ID"]
            for _, fila in datos.iterrows()
        }
        seleccionado = st.selectbox("Selecciona a la persona", list(opciones_registro.keys()))
        confirmar = st.checkbox("Confirmo que deseo eliminar el registro.")
        if st.button("Eliminar", type="primary"):
            if confirmar:
                id_eliminar = opciones_registro[seleccionado]
                datos = datos[datos["ID"] != id_eliminar].copy()
                guardar_datos(datos)
                st.success("Registro eliminado.")
                st.rerun()
            else:
                st.warning("Confirma la eliminación.")


elif opcion == "Gráfica de partidos":
    st.subheader("Cantidad de registros por partido")
    if datos.empty:
        st.info("Registra personas para generar la gráfica.")
    else:
        conteo = datos["Partido"].value_counts()
        st.bar_chart(conteo, x_label="Partido", y_label="Cantidad de registros")
        st.dataframe(
            conteo.rename("Cantidad").reset_index(),
            use_container_width=True,
            hide_index=True
        )
        st.caption("La gráfica muestra registros administrativos, no votos emitidos ni resultados oficiales.")


elif opcion == "Administrar usuarios" and rol_actual == "admin":
    st.subheader("Administrar acceso al sistema")

    with st.form("nuevo_usuario"):
        nuevo_nombre = st.text_input("Nombre del nuevo usuario")
        nueva_clave = st.text_input("Contraseña (mínimo 12 caracteres)", type="password")
        repetir_clave = st.text_input("Confirmar contraseña", type="password")
        crear = st.form_submit_button("Autorizar usuario")

    if crear:
        nuevo_nombre = nuevo_nombre.strip()
        if not nuevo_nombre:
            st.error("Escribe el nombre del usuario.")
        elif nuevo_nombre in usuarios:
            st.error("Ese usuario ya existe.")
        elif len(nueva_clave) < 12:
            st.error("La contraseña debe tener al menos 12 caracteres.")
        elif nueva_clave != repetir_clave:
            st.error("Las contraseñas no coinciden.")
        else:
            crear_usuario(usuarios, nuevo_nombre, nueva_clave, rol="usuario")
            st.success("Usuario autorizado.")
            st.rerun()

    st.markdown("### Usuarios existentes")
    for nombre, info in list(usuarios.items()):
        c1, c2, c3 = st.columns([3, 2, 2])
        c1.write(f"**{nombre}**")
        c2.write(f"{info['rol']} — {'Activo' if info['activo'] else 'Desactivado'}")
        if nombre != usuario_actual:
            if info["activo"]:
                if c3.button("Desactivar", key=f"off_{nombre}"):
                    usuarios[nombre]["activo"] = False
                    guardar_usuarios(usuarios)
                    st.rerun()
            else:
                if c3.button("Activar", key=f"on_{nombre}"):
                    usuarios[nombre]["activo"] = True
                    guardar_usuarios(usuarios)
                    st.rerun()
        else:
            c3.caption("Sesión actual")


elif opcion == "Historial de accesos" and rol_actual == "admin":
    st.subheader("Historial de inicios de sesión")
    contenido = leer_accesos()
    st.text_area("Eventos registrados (no se guardan contraseñas)", contenido, height=350)
    st.download_button(
        "Descargar accesos.txt",
        data=contenido,
        file_name="accesos.txt",
        mime="text/plain"
    )
    st.caption(
        "El historial puede incluir nombres de usuario e intentos fallidos. "
        "Limita su acceso a administradores."
    )

